"""Receipt & Document Parser.
Extracts structured merchant metadata, verified addresses, financial totals,
and itemized line items into StandardizedReceipt objects using multimodal LLM
or rule-based heuristic extraction.
"""

from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from liftassistant.llm import call_vision_llm
from liftassistant.models.domain import ReceiptLineItem, StandardizedReceipt
from liftassistant.services.image_ocr import extract_text_from_receipt_image

logger = logging.getLogger(__name__)

# Known local Cranberry Township merchant lookup table for reliable geocoding & address matching
KNOWN_MERCHANTS: Dict[str, Dict[str, Any]] = {
    "costco": {
        "name": "Costco Wholesale #1024",
        "address": "1050 Cranberry Square Dr, Cranberry Twp, PA 16066",
        "category": "supermarket",
        "place_id": "pl_costco",
    },
    "mad mex": {
        "name": "Mad Mex Cranberry",
        "address": "20510 Rte 19, Cranberry Twp, PA 16066",
        "category": "dining",
        "place_id": "pl_madmex",
    },
    "olive garden": {
        "name": "Olive Garden Italian Restaurant",
        "address": "1716 Route 228, Cranberry Twp, PA 16066",
        "category": "dining",
        "place_id": "pl_olivegarden",
    },
    "valvoline": {
        "name": "Valvoline Instant Oil Change",
        "address": "20120 Rte 19, Cranberry Twp, PA 16066",
        "category": "service",
        "place_id": "pl_valvoline",
    },
    "giant eagle": {
        "name": "Giant Eagle Supermarket",
        "address": "20675 Rte 19, Cranberry Twp, PA 16066",
        "category": "supermarket",
        "place_id": "pl_ge",
    },
    "trader joe": {
        "name": "Trader Joe's",
        "address": "8000 McKnight Rd, Pittsburgh, PA 15237",
        "category": "supermarket",
        "place_id": "pl_tj",
    },
    "oriental market": {
        "name": "Oriental Market",
        "address": "4768 McKnight Rd, Pittsburgh, PA 15237",
        "category": "supermarket",
        "place_id": "pl_oriental",
    },
    "ymca": {
        "name": "Rose E. Schneider Family YMCA",
        "address": "2001 Ehrman Rd, Cranberry Twp, PA 16066",
        "category": "gym",
        "place_id": "pl_ymca",
    },
    "primrose": {
        "name": "Primrose School of Wexford",
        "address": "2598 Wexford Bayne Rd, Sewickley, PA 15143",
        "category": "education",
        "place_id": "pl_primrose",
    },
    "lowes": {
        "name": "Lowe's Home Improvement",
        "address": "20000 Route 19, Cranberry Twp, PA 16066",
        "category": "hardware",
        "place_id": "pl_lowes",
    },
}

# Department mapping for Costco warehouse exports
COSTCO_DEPT_CATEGORY_MAP: Dict[int, str] = {
    11: "groceries",
    12: "groceries",   # Candy & Snacks
    13: "groceries",   # Packaged Foods / Pantry
    14: "bakery",
    17: "dairy",       # Milk, Butter, Cheese
    18: "seafood",     # Fresh & Frozen Seafood
    19: "frozen",
    61: "meat",        # Fresh Meat / Pork / Beef
    65: "produce",     # Fresh Fruit & Vegetables
    93: "pharmacy",    # Vitamins, OTC, Health
    84: "clothing",
    23: "electronics",
    31: "hardware",
}

# Product matching map for Grocy catalog
PRODUCT_KEYWORD_MAP: Dict[str, str] = {
    "bath tissue": "prod_tp",
    "toilet paper": "prod_tp",
    "kirkland bath": "prod_tp",
    "whole milk": "prod_milk",
    "organic milk": "prod_milk",
    "a2 whole milk": "prod_milk",
    "a2 milk": "prod_milk",
    "milk": "prod_milk",
    "brown eggs": "prod_eggs",
    "pasture eggs": "prod_eggs",
    "eggs": "prod_eggs",
    "dishwasher pods": "prod_pods",
    "cascade": "prod_pods",
    "paper towels": "prod_pt",
    "bananas": "prod_banana",
    "banana": "prod_banana",
    "yogurt": "prod_yogurt",
    "salmon": "prod_salmon",
    "canola": "prod_canola",
    "fr 2dz": "prod_eggs",
}


class ReceiptParser:
    """Parser to transform OCR text, digital JSON exports, or image contents into StandardizedReceipt domain models."""

    def parse_from_file(
        self,
        file_path: Union[str, Path],
        file_hash: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> StandardizedReceipt:
        """Parse receipt directly from a file path on disk (JSON export or text/OCR)."""
        receipts = self.parse_all_from_file(file_path, file_hash, source_channel)
        if not receipts:
            raise ValueError(f"No receipts could be parsed from {file_path}")
        return receipts[0]

    def parse_all_from_file(
        self,
        file_path: Union[str, Path],
        file_hash: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> List[StandardizedReceipt]:
        """Parse all receipts from a file path (supports bundled JSON exports or single receipts)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Receipt file not found: {file_path}")

        content_bytes = path.read_bytes()
        computed_hash = file_hash or hashlib.sha256(content_bytes).hexdigest()

        # Handle image files via Multimodal Vision LLM (single receipt image)
        if path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
            return [self.parse_from_image(
                image_path=path,
                file_hash=computed_hash,
                source_channel=source_channel or "PHOTO_CAMERA",
            )]

        # Handle JSON files (supports single receipt object or array of bundled receipts)
        if path.suffix.lower() == ".json":
            try:
                return self.parse_all_from_json(
                    json_data=content_bytes.decode("utf-8"),
                    file_hash=computed_hash,
                    file_path=str(path),
                    original_filename=path.name,
                    source_channel=source_channel or "COSTCO_APP_JSON",
                )
            except Exception as e:
                logger.warning("JSON parsing failed, falling back to text: %s", e)

        # Handle PDF files using PyMuPDF (fitz) or pdfplumber
        if path.suffix.lower() == ".pdf":
            try:
                import fitz
                doc = fitz.open(path)
                pdf_text = "\n".join([page.get_text() for page in doc])
                doc.close()
                if pdf_text.strip():
                    return [self.parse_from_text(
                        raw_text=pdf_text,
                        file_hash=computed_hash,
                        file_path=str(path),
                        original_filename=path.name,
                        source_channel=source_channel or "PDF_INVOICE",
                    )]
            except Exception as e:
                logger.warning("PDF extraction failed: %s", e)

        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = f"Binary receipt: {path.name}"

        return [self.parse_from_text(
            raw_text=text,
            file_hash=computed_hash,
            file_path=str(path),
            original_filename=path.name,
            source_channel=source_channel or "FILE_IMPORT",
        )]

    def parse_from_image(
        self,
        image_path: Union[str, Path],
        file_hash: str,
        source_channel: str = "PHOTO_CAMERA",
    ) -> StandardizedReceipt:
        """Parse receipt image using Multimodal Vision LLM (with OCR fallback)."""
        path = Path(image_path)
        img_bytes = path.read_bytes()

        # Step 1: Preprocess orientation with PIL so LLM sees it upright
        try:
            from PIL import Image, ImageOps
            import io
            with Image.open(path) as im:
                im_upright = ImageOps.exif_transpose(im)
                im_upright.thumbnail((1400, 1800))
                buf = io.BytesIO()
                im_upright.save(buf, format="JPEG", quality=85)
                upright_bytes = buf.getvalue()
        except Exception:
            upright_bytes = img_bytes

        # Helper to extract capture time from EXIF metadata
        def _get_exif_capture_time(img_path: Path) -> Optional[datetime]:
            try:
                from PIL import Image
                from dateutil import parser as dt_parser
                with Image.open(img_path) as im:
                    exif = im.getexif()
                    if exif:
                        for tag_id in (36867, 306, 36868):  # DateTimeOriginal, DateTime, DateTimeDigitized
                            val = exif.get(tag_id)
                            if val:
                                cleaned = str(val).replace(":", "-", 2)
                                return dt_parser.parse(cleaned, fuzzy=True).replace(tzinfo=None)
            except Exception:
                pass
            return None

        # Step 2: Attempt Multimodal Vision LLM extraction
        prompt = (
            "You are an expert receipt parser. Extract all structured details from this receipt image. "
            "Return ONLY a valid JSON object with these exact keys:\n"
            "{\n"
            '  "merchant_name": string,\n'
            '  "merchant_address": string,\n'
            '  "category": "DINING" | "SHOPPING",\n'
            '  "transaction_time": string (e.g. "YYYY-MM-DD HH:MM:SS" or "Month DD, YYYY HH:MM:SS AM/PM" or date as shown on receipt),\n'
            '  "subtotal": float,\n'
            '  "tax_amount": float,\n'
            '  "tip_amount": float,\n'
            '  "total_amount": float,\n'
            '  "line_items": [\n'
            '    {"name": string, "quantity": float, "unit_price": float, "total_price": float}\n'
            "  ]\n"
            "}\n"
            "CATEGORY GUIDELINE: Set category to 'DINING' if the merchant is a restaurant, cafe, bar, eatery, diner, fast food, bakery, food truck, or serves prepared meals/drinks; set to 'SHOPPING' for grocery stores, supermarkets, pharmacies, retail stores, gas stations, hardware stores.\n"
            "Look carefully across the header, footer, terminal info, register timestamps, and barcodes for the date and time. "
            "If only date is visible, include the date.\n"
            "CRITICAL: 'total_amount' MUST be the exact final bottom-line amount charged/paid by the customer (Grand Total / Total / Amount Paid). "
            "Do NOT add tax to total_amount if tax is already included or if discounts apply."
        )

        try:
            llm_res = call_vision_llm(prompt=prompt, image_bytes=upright_bytes)
            if llm_res:
                data = json.loads(llm_res)
                if isinstance(data, dict) and ("merchant_name" in data or "total_amount" in data or "line_items" in data or "items" in data):
                    receipt = self._parse_generic_json(
                        receipt_dict=data,
                        raw_payload=data,
                        file_hash=file_hash,
                        file_path=str(path),
                        original_filename=path.name,
                        source_channel="VISION_LLM",
                    )
                    if receipt.transaction_time is None:
                        receipt.transaction_time = _get_exif_capture_time(path)
                    if receipt.transaction_time is None and source_channel in ("PHOTO_CAMERA", "CAMERA"):
                        receipt.transaction_time = datetime.now()
                    elif receipt.transaction_time:
                        current_year = datetime.now().year
                        # Correct LLM year hallucination when month & day match today or raw receipt text contains current year
                        if receipt.transaction_time.year < current_year:
                            if receipt.transaction_time.month == datetime.now().month and receipt.transaction_time.day == datetime.now().day:
                                receipt.transaction_time = receipt.transaction_time.replace(year=current_year)
                            else:
                                ocr_snippet = extract_text_from_receipt_image(path)
                                if str(current_year) in ocr_snippet:
                                    receipt.transaction_time = receipt.transaction_time.replace(year=current_year)
                    return receipt
        except Exception as e:
            logger.info("Vision LLM parsing unavailable or bypassed (%s), falling back to OCR", e)

        # Step 3: Fallback to OCR text parsing
        ocr_text = extract_text_from_receipt_image(path)
        receipt = self.parse_from_text(
            raw_text=ocr_text,
            file_hash=file_hash,
            file_path=str(path),
            original_filename=path.name,
            source_channel=source_channel,
        )
        if receipt.transaction_time is None:
            receipt.transaction_time = _get_exif_capture_time(path)
        if receipt.transaction_time is None and source_channel in ("PHOTO_CAMERA", "CAMERA"):
            receipt.transaction_time = datetime.now()
        return receipt

    def parse_from_json(
        self,
        json_data: Union[str, Dict[str, Any], List[Any]],
        file_hash: str,
        file_path: str,
        original_filename: Optional[str] = None,
        source_channel: str = "COSTCO_APP_JSON",
    ) -> StandardizedReceipt:
        """Parse structured digital receipt JSON exports (single receipt)."""
        receipts = self.parse_all_from_json(
            json_data=json_data,
            file_hash=file_hash,
            file_path=file_path,
            original_filename=original_filename,
            source_channel=source_channel,
        )
        if not receipts:
            raise ValueError("No valid receipts found in JSON payload")
        return receipts[0]

    def parse_all_from_json(
        self,
        json_data: Union[str, Dict[str, Any], List[Any]],
        file_hash: str,
        file_path: str,
        original_filename: Optional[str] = None,
        source_channel: str = "COSTCO_APP_JSON",
    ) -> List[StandardizedReceipt]:
        """Parse structured digital receipt JSON exports, supporting single receipts or bundled multi-receipt arrays."""
        if isinstance(json_data, str):
            parsed = json.loads(json_data)
        else:
            parsed = json_data

        if isinstance(parsed, list):
            receipt_list = parsed
        elif isinstance(parsed, dict):
            receipt_list = [parsed]
        else:
            raise ValueError(f"Unsupported JSON receipt payload type: {type(parsed)}")

        results: List[StandardizedReceipt] = []
        for r_dict in receipt_list:
            if not isinstance(r_dict, dict):
                continue

            # Detect Costco Warehouse Receipt schema
            is_costco = (
                r_dict.get("documentType") == "WarehouseReceiptDetail"
                or "itemArray" in r_dict
                or "warehouseNumber" in r_dict
                or "warehouseAddress1" in r_dict
                or "warehouseShortName" in r_dict
            )

            if is_costco:
                results.append(
                    self._parse_costco_json(
                        receipt_dict=r_dict,
                        raw_payload=r_dict,
                        file_hash=file_hash,
                        file_path=file_path,
                        original_filename=original_filename,
                        source_channel=source_channel,
                    )
                )
            else:
                results.append(
                    self._parse_generic_json(
                        receipt_dict=r_dict,
                        raw_payload=r_dict,
                        file_hash=file_hash,
                        file_path=file_path,
                        original_filename=original_filename,
                        source_channel=source_channel,
                    )
                )
        return results

    def _parse_costco_json(
        self,
        receipt_dict: Dict[str, Any],
        raw_payload: Any,
        file_hash: str,
        file_path: str,
        original_filename: Optional[str] = None,
        source_channel: str = "COSTCO_APP_JSON",
    ) -> StandardizedReceipt:
        """Parse official Costco app / web warehouse receipt JSON."""
        # 1. Merchant & Grounded Address
        wh_num = receipt_dict.get("warehouseNumber") or "1024"
        wh_name = receipt_dict.get("warehouseShortName") or receipt_dict.get("warehouseName") or "Cranberry Twp"
        merchant_name = f"Costco Wholesale #{wh_num} ({wh_name.title()})"

        addr1 = receipt_dict.get("warehouseAddress1") or ""
        city = receipt_dict.get("warehouseCity") or ""
        state = receipt_dict.get("warehouseState") or ""
        zip_code = receipt_dict.get("warehousePostalCode") or ""
        formatted_addr = f"{addr1}, {city}, {state} {zip_code}".strip(", ")
        merchant_address = (
            receipt_dict.get("warehouseFullAddress")
            or formatted_addr
            or "1050 Cranberry Square Dr, Cranberry Twp, PA 16066"
        )

        # Resolve verified place_id
        place_id: Optional[str] = "pl_costco"
        for key, info in KNOWN_MERCHANTS.items():
            if key in merchant_address.lower() or key in merchant_name.lower():
                place_id = info["place_id"]
                break

        # 2. Transaction Time
        tx_time: Optional[datetime] = None
        tx_str = (
            receipt_dict.get("transactionDateTime")
            or receipt_dict.get("transactionDateISO")
            or receipt_dict.get("transactionDate")
        )
        if tx_str and str(tx_str).lower() not in ("null", "none", "unknown", ""):
            try:
                from dateutil import parser as dt_parser
                tx_time = dt_parser.parse(str(tx_str), fuzzy=True).replace(tzinfo=None)
            except Exception:
                try:
                    dt = datetime.fromisoformat(str(tx_str).replace("Z", "+00:00"))
                    tx_time = dt.replace(tzinfo=None)
                except Exception:
                    tx_time = None

        # 3. Totals
        total_amount = float(receipt_dict.get("total") or 0.0)
        subtotal = float(receipt_dict.get("subTotal") or total_amount)
        tax_amount = float(receipt_dict.get("taxes") or 0.0)
        tip_amount = 0.0

        # 4. Line Items
        line_items: List[ReceiptLineItem] = []
        for itm in receipt_dict.get("itemArray", []):
            raw_name = itm.get("itemActualName") or itm.get("itemDescription01") or "Item"
            item_num = str(itm.get("itemNumber") or "")
            unit_val = float(itm.get("unit") or 1.0)
            amount = float(itm.get("amount") or 0.0)
            unit_price_val = float(itm.get("itemUnitPriceAmount") or 0.0)

            # Check if this is an Instant Savings coupon / discount line
            if amount < 0 or unit_val < 0 or raw_name.startswith("/"):
                target_item = raw_name.lstrip("/") if raw_name.startswith("/") else item_num
                clean_name = f"Instant Savings (Item #{target_item})" if target_item else "Instant Savings Discount"
                category = "discount"
                qty = abs(unit_val)
                unit_p = amount
                u = "ea"
                matched_pid = None
            else:
                clean_name = raw_name
                dept_num = itm.get("itemDepartmentNumber") or itm.get("transDepartmentNumber")
                category = COSTCO_DEPT_CATEGORY_MAP.get(dept_num, "groceries")

                # Weighted items (e.g. "Pork Belly ... Per Lb.")
                if "per lb" in clean_name.lower() and unit_price_val > 0 and abs(amount - unit_price_val) > 0.01:
                    qty = round(amount / unit_price_val, 2)
                    u = "lb"
                    unit_p = unit_price_val
                else:
                    qty = max(1.0, unit_val)
                    unit_p = unit_price_val if unit_price_val > 0 else round(amount / qty, 2)
                    u = "pack" if any(w in clean_name.lower() for w in ["pack", "count", "ct", "pk", "count"]) else "ea"

                # Link with Grocy product catalog if matched
                matched_pid = None
                clean_lower = clean_name.lower()
                for keyword, pid in PRODUCT_KEYWORD_MAP.items():
                    if keyword in clean_lower:
                        matched_pid = pid
                        break

            line_items.append(ReceiptLineItem(
                raw_text=f"{clean_name} x{qty} ${amount:.2f}",
                clean_name=clean_name,
                category=category,
                quantity=qty,
                unit=u,
                unit_price=unit_p,
                total_price=amount,
                product_id=matched_pid,
            ))

        # Unique receipt reference ID (Costco transactionBarcode or composite key)
        barcode = receipt_dict.get("transactionBarcode")
        reg_num = receipt_dict.get("registerNumber")
        tran_num = receipt_dict.get("transactionNumber")
        tran_date = receipt_dict.get("transactionDate")
        ref_id = str(barcode) if barcode else f"costco_{wh_num}_{reg_num}_{tran_num}_{tran_date}"

        return StandardizedReceipt(
            event_id=None,
            place_id=place_id,
            file_hash=file_hash,
            file_path=file_path,
            original_filename=original_filename,
            merchant_name=merchant_name,
            merchant_address=merchant_address,
            transaction_time=tx_time,
            subtotal=subtotal or (total_amount - tax_amount - tip_amount),
            tax_amount=tax_amount,
            tip_amount=tip_amount,
            total_amount=total_amount,
            currency="USD",
            source_channel=source_channel,
            source_reference_id=ref_id,
            raw_ocr_json=json.dumps(raw_payload) if not isinstance(raw_payload, str) else raw_payload,
            parsing_status="SUCCESS",
            line_items=line_items,
        )

    def _parse_generic_json(
        self,
        receipt_dict: Dict[str, Any],
        raw_payload: Any,
        file_hash: str,
        file_path: str,
        original_filename: Optional[str] = None,
        source_channel: str = "DIGITAL_RECEIPT",
    ) -> StandardizedReceipt:
        """Fallback parser for standard generic digital receipts."""
        merchant_name = (
            receipt_dict.get("merchant_name")
            or receipt_dict.get("merchant")
            or receipt_dict.get("store")
            or "General Merchant"
        )
        merchant_address = (
            receipt_dict.get("merchant_address")
            or receipt_dict.get("address")
            or "Cranberry Twp, PA"
        )
        total_amount = float(receipt_dict.get("total_amount") or receipt_dict.get("total") or 0.0)
        subtotal = float(receipt_dict.get("subtotal") or receipt_dict.get("subTotal") or total_amount)
        tax_amount = float(receipt_dict.get("tax_amount") or receipt_dict.get("tax") or 0.0)
        tip_amount = float(receipt_dict.get("tip_amount") or receipt_dict.get("tip") or 0.0)

        place_id: Optional[str] = None
        for key, info in KNOWN_MERCHANTS.items():
            if key in merchant_name.lower() or key in merchant_address.lower():
                place_id = info["place_id"]
                break

        line_items: List[ReceiptLineItem] = []
        raw_items = receipt_dict.get("line_items") or receipt_dict.get("items") or []
        for itm in raw_items:
            name = itm.get("clean_name") or itm.get("name") or itm.get("description") or "Item"
            qty = float(itm.get("quantity") or itm.get("qty") or 1.0)
            tot_price = float(itm.get("total_price") or itm.get("amount") or itm.get("price") or 0.0)
            unit_p = float(itm.get("unit_price") or (tot_price / qty if qty > 0 else tot_price))

            matched_pid = None
            clean_lower = name.lower()
            for keyword, pid in PRODUCT_KEYWORD_MAP.items():
                if keyword in clean_lower:
                    matched_pid = pid
                    break

            line_items.append(ReceiptLineItem(
                raw_text=f"{name} x{qty} ${tot_price:.2f}",
                clean_name=name,
                category=itm.get("category", "groceries"),
                quantity=qty,
                unit=itm.get("unit", "ea"),
                unit_price=unit_p,
                total_price=tot_price,
                product_id=matched_pid,
            ))

        tx_time: Optional[datetime] = None
        tx_str = receipt_dict.get("transaction_time") or receipt_dict.get("date") or receipt_dict.get("datetime")
        if tx_str and str(tx_str).lower() not in ("null", "none", "unknown", ""):
            try:
                from dateutil import parser as dt_parser
                parsed = dt_parser.parse(str(tx_str), fuzzy=True)
                tx_time = parsed.replace(tzinfo=None)
            except Exception:
                try:
                    cleaned_str = str(tx_str).replace("/", "-").strip()
                    if "T" in cleaned_str:
                        tx_time = datetime.fromisoformat(cleaned_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    tx_time = None

        ref_id = (
            receipt_dict.get("source_reference_id")
            or receipt_dict.get("invoiceNumber")
            or receipt_dict.get("orderNumber")
            or receipt_dict.get("id")
        )
        if not ref_id:
            time_part = tx_time.isoformat() if tx_time else datetime.now().isoformat()
            ref_id = f"{merchant_name.strip().lower()}_{time_part}_{total_amount:.2f}"

        category = str(receipt_dict.get("category", "")).upper() or None
        if not category and tip_amount > 0.0:
            category = "DINING"

        return StandardizedReceipt(
            event_id=None,
            place_id=place_id,
            file_hash=file_hash,
            file_path=file_path,
            original_filename=original_filename,
            merchant_name=merchant_name,
            merchant_address=merchant_address,
            transaction_time=tx_time,
            subtotal=subtotal,
            tax_amount=tax_amount,
            tip_amount=tip_amount,
            total_amount=total_amount,
            currency="USD",
            category=category,
            source_channel=source_channel,
            source_reference_id=ref_id,
            raw_ocr_json=json.dumps(raw_payload) if not isinstance(raw_payload, str) else raw_payload,
            parsing_status="SUCCESS",
            line_items=line_items,
        )

    def parse_from_text(
        self,
        raw_text: str,
        file_hash: str,
        file_path: str,
        original_filename: Optional[str] = None,
        source_channel: str = "PHOTO_CAMERA",
    ) -> StandardizedReceipt:
        """Heuristic rule-based parser for text, receipt OCR transcripts, CSV content, or JSON."""
        # 0. Check if raw_text is valid JSON (Costco export or generic JSON)
        trimmed = raw_text.strip()
        if trimmed.startswith(("{", "[")):
            try:
                data = json.loads(trimmed)
                return self.parse_from_json(
                    json_data=data,
                    file_hash=file_hash,
                    file_path=file_path,
                    original_filename=original_filename,
                    source_channel="COSTCO_APP_JSON" if "WarehouseReceipt" in trimmed or "itemArray" in trimmed else "DIGITAL_RECEIPT",
                )
            except (json.JSONDecodeError, ValueError):
                pass  # Fallback to line-by-line OCR text parser

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        # 1. Merchant & Address Extraction
        merchant_name = "General Merchant"
        merchant_address = "Cranberry Twp, PA"
        place_id: Optional[str] = None

        text_lower = raw_text.lower()
        for key, info in KNOWN_MERCHANTS.items():
            if (
                key in text_lower
                or (key == "costco" and any(w in text_lower for w in ["cesrco", "cranberry square", "costco wallet"]))
                or (key == "oriental market" and any(w in text_lower for w in ["oriental", "mcknight", "陡 軎"]))
            ):
                merchant_name = info["name"]
                merchant_address = info["address"]
                place_id = info["place_id"]
                break

        # Fallback to first line if no known merchant matched
        if merchant_name == "General Merchant" and lines:
            merchant_name = lines[0][:40]

        # 1.5 Date & Time Extraction
        tx_time: Optional[datetime] = None
        date_patterns = [
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
            r"\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
            r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{2,4})\b",
            r"\b(\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{2,4})\b",
        ]
        time_match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)", raw_text)
        time_str = time_match.group(1).strip() if time_match else ""

        for pat in date_patterns:
            dm = re.search(pat, raw_text, re.IGNORECASE)
            if dm:
                candidate = f"{dm.group(1)} {time_str}".strip()
                try:
                    from dateutil import parser as dt_parser
                    parsed = dt_parser.parse(candidate, fuzzy=True)
                    tx_time = parsed.replace(tzinfo=None)
                    break
                except Exception:
                    pass

        # 2. Financial Totals Extraction
        total_amount = 0.0
        tax_amount = 0.0
        tip_amount = 0.0
        subtotal = 0.0

        for line in lines:
            line_l = line.lower()
            amounts = re.findall(r"\$?\s*(\d+\.\d{2})", line)
            if not amounts:
                continue

            last_amt = float(amounts[-1])
            if "total" in line_l and "sub" not in line_l and "item" not in line_l:
                total_amount = max(total_amount, last_amt)
            elif "subtotal" in line_l or "subtot" in line_l:
                subtotal = last_amt
            elif "tax" in line_l:
                tax_amount = last_amt
            elif "tip" in line_l:
                tip_amount = last_amt

        if total_amount == 0.0 and subtotal > 0.0:
            total_amount = subtotal + tax_amount + tip_amount
        elif subtotal == 0.0 and total_amount > 0.0:
            subtotal = total_amount - tax_amount - tip_amount

        # 3. Line Items Extraction
        line_items: List[ReceiptLineItem] = []
        item_counter = 0
        for line in lines:
            line_clean = line.strip()
            line_l = line_clean.lower()

            # Skip header/total rows, tender info, card hashes
            if any(k in line_l for k in [
                "total", "subtotal", "subtot", "tax", "balance", "visa", "mastercard",
                "wallet", "tender", "change", "linked cc", "approved", "member",
                "seq#", "tran id", "op#", "items sold", "thank you", "count :",
                "number of items", "cranberry square", "mcknight"
            ]):
                continue

            # Check if line resembles an item with a price
            match = re.search(r"^(.*?)(?:\s+x?(\d+))?\s+\$?(\d+\.\d{2})$", line_clean)
            if match:
                raw_desc = match.group(1).strip()
                qty_str = match.group(2)
                price_str = match.group(3)
                total_p = float(price_str)

                # Skip zero amounts with short codes (e.g. tax codes like "av 0.00")
                if total_p == 0.0 and len(raw_desc) <= 4:
                    continue

                # Strip leading tax flags like "E " or "A "
                clean_name = re.sub(r"^[EA]\s+", "", raw_desc).strip()
                if not clean_name:
                    item_counter += 1
                    clean_name = f"Grocery Item #{item_counter}"

                qty = float(qty_str) if qty_str else 1.0
                unit_p = round(total_p / max(1.0, qty), 2)

                # Link with product catalog if matched
                matched_prod_id = None
                clean_lower = clean_name.lower()
                for keyword, pid in PRODUCT_KEYWORD_MAP.items():
                    if keyword in clean_lower:
                        matched_prod_id = pid
                        break

                item = ReceiptLineItem(
                    raw_text=line_clean,
                    clean_name=clean_name,
                    category="groceries" if ("costco" in text_lower or "trader" in text_lower or "oriental" in text_lower) else "general",
                    quantity=qty,
                    unit="ea",
                    unit_price=unit_p,
                    total_price=total_p,
                    product_id=matched_prod_id,
                )
                line_items.append(item)
            else:
                # Standalone price line without recognized description
                price_only = re.search(r"^\$?(\d+\.\d{2})$", line_clean)
                if price_only:
                    price_val = float(price_only.group(1))
                    if price_val > 0.0 and abs(price_val - total_amount) > 0.01 and abs(price_val - subtotal) > 0.01:
                        item_counter += 1
                        line_items.append(ReceiptLineItem(
                            raw_text=line_clean,
                            clean_name=f"Grocery Item #{item_counter}",
                            category="groceries",
                            quantity=1.0,
                            unit="ea",
                            unit_price=price_val,
                            total_price=price_val,
                            product_id=None,
                        ))

        return StandardizedReceipt(
            event_id=None,
            place_id=place_id,
            file_hash=file_hash,
            file_path=file_path,
            original_filename=original_filename,
            merchant_name=merchant_name,
            merchant_address=merchant_address,
            transaction_time=tx_time,
            subtotal=subtotal or (total_amount - tax_amount - tip_amount),
            tax_amount=tax_amount,
            tip_amount=tip_amount,
            total_amount=total_amount,
            source_channel=source_channel,
            raw_ocr_json=json.dumps({"line_count": len(lines), "raw_preview": lines[:10]}),
            parsing_status="SUCCESS",
            line_items=line_items,
        )
