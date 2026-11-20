"""Windows & Cross-Platform OCR Service for Receipt Images.

Utilizes PIL for EXIF orientation normalization, followed by Windows.Media.Ocr
or fallback OCR to extract words and spatial bounding boxes. Merges words
spatially into coherent lines so that multi-column store receipts (item name
on left, price on right) can be parsed cleanly.
"""

import json
import logging
from pathlib import Path
import platform
import re
import subprocess
from typing import List, Optional, Union
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

PS_OCR_SCRIPT = """param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath,
    [string]$LanguageTag = ""
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$fullPath = [System.IO.Path]::GetFullPath($ImagePath)
$fileStream = [System.IO.File]::OpenRead($fullPath)
$ras = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fileStream)
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

if ($LanguageTag -ne "") {
    $lang = [Windows.Globalization.Language]::new($LanguageTag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$linesData = @()
foreach ($line in $result.Lines) {
    $wordsData = @()
    foreach ($w in $line.Words) {
        $wordsData += @{
            text = $w.Text
            x = [math]::Round($w.BoundingRect.X, 1)
            y = [math]::Round($w.BoundingRect.Y, 1)
            w = [math]::Round($w.BoundingRect.Width, 1)
            h = [math]::Round($w.BoundingRect.Height, 1)
        }
    }
    $linesData += @{
        text = $line.Text
        words = $wordsData
    }
}
$fileStream.Close()

$output = @{
    lines = $linesData
}
$output | ConvertTo-Json -Depth 5
"""


def extract_text_from_receipt_image(
    image_path: Union[str, Path],
    lang: str = "",
    y_threshold: float = 20.0,
) -> str:
    """Extract and reconstruct spatial text from a receipt image.

    Args:
        image_path: Absolute or relative path to the image file.
        lang: Optional Windows BCP-47 language tag (e.g. 'en-US', 'zh-Hans-CN').
        y_threshold: Pixel vertical tolerance for clustering words into the same line.

    Returns:
        Reconstructed multi-line plain text transcript of the receipt.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Receipt image not found: {image_path}")

    # 1. Correct EXIF orientation
    temp_upright = path.parent / f"_temp_upright_{path.name}"
    try:
        with Image.open(path) as im:
            im_trans = ImageOps.exif_transpose(im)
            im_trans.save(temp_upright)
    except Exception as e:
        logger.warning("Could not apply EXIF transpose to %s: %s", path, e)
        temp_upright = path

    # 2. Run OCR (Windows Media OCR if on Windows)
    ps_file = path.parent / f"_temp_ocr_{path.stem}.ps1"
    try:
        if platform.system() == "Windows":
            ps_file.write_text(PS_OCR_SCRIPT, encoding="utf-8")
            cmd = [
                "powershell",
                "-ExecutionPolicy", "Bypass",
                "-File", str(ps_file),
                "-ImagePath", str(temp_upright),
            ]
            if lang:
                cmd.extend(["-LanguageTag", lang])

            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if res.returncode != 0:
                logger.error("PowerShell OCR failed: %s", res.stderr)
                return ""

            stdout = res.stdout.strip()
            json_start = stdout.find("{")
            if json_start == -1:
                return ""

            data = json.loads(stdout[json_start:])
            all_words = []
            for line in data.get("lines", []):
                for w in line.get("words", []):
                    all_words.append(w)

            if not all_words:
                return ""

            # Sort words primarily by y, then by x
            all_words.sort(key=lambda w: (w["y"], w["x"]))

            # Cluster words into horizontal lines
            clusters = []
            for w in all_words:
                matched = False
                w_mid_y = w["y"] + w["h"] / 2.0
                for cluster in clusters:
                    cluster_mid_y = sum(cw["y"] + cw["h"] / 2.0 for cw in cluster) / len(cluster)
                    if abs(w_mid_y - cluster_mid_y) <= y_threshold:
                        cluster.append(w)
                        matched = True
                        break
                if not matched:
                    clusters.append([w])

            clusters.sort(key=lambda c: sum(w["y"] for w in c) / len(c))

            merged_lines = []
            for cluster in clusters:
                cluster.sort(key=lambda w: w["x"])
                text = " ".join(w["text"] for w in cluster)
                # Normalize full-width punctuation & OCR spacing quirks
                text = (
                    text.replace("，", ",")
                    .replace("．", ".")
                    .replace("、", ".")
                    .replace("＄", "$")
                    .replace("：", ":")
                )
                text = re.sub(r"\$\s*(\d+)[\.,\s]+(\d{2})\b", r"$\1.\2", text)
                text = re.sub(r"\b(\d+)[\,](\d{2})\b", r"\1.\2", text)
                merged_lines.append(text)

            return "\n".join(merged_lines)
        else:
            logger.warning("Windows Media OCR not supported on non-Windows platform %s", platform.system())
            return ""

    finally:
        if temp_upright.exists() and temp_upright != path:
            try:
                temp_upright.unlink()
            except Exception:
                pass
        if ps_file.exists():
            try:
                ps_file.unlink()
            except Exception:
                pass
