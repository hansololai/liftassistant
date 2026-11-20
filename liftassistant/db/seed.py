"""Seed data population for LiftAssistant 3.0 SQLite ledger."""

import json
import logging
from pathlib import Path
from typing import Optional
from liftassistant.db.connection import get_db

logger = logging.getLogger(__name__)


def seed_database(db_path: Optional[Path] = None) -> None:
    """Populate default baseline data into SQLite."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # 1. Family Members
        people_data = [
            ("p_dad", "Dad", "parent", "blue"),
            ("p_mom", "Mom", "parent", "pink"),
            ("p_marcus", "Marcus", "child", "green"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO people (id, name, role, color) VALUES (?, ?, ?, ?)",
            people_data,
        )

        # 2. Places & Venues
        places_data = [
            (
                "pl_ymca",
                "Rose E. Schneider Family YMCA",
                "gym",
                "2001 Ehrman Rd, Cranberry Twp, PA 16066",
                40.7021,
                -80.1245,
                "https://maps.google.com/?q=Rose+E+Schneider+YMCA",
                "ChIJ51c9R...YMCA",
                "Warm Water Pool is in Aquatic Wing. Door code for family locker room.",
            ),
            (
                "pl_madmex",
                "Mad Mex",
                "restaurant",
                "20510 Rte 19, Cranberry Twp, PA 16066",
                40.6923,
                -80.1082,
                "https://maps.google.com/?q=Mad+Mex+Cranberry",
                "ChIJ9xX7...MadMex",
                "Good family tacos, outdoor patio in summer.",
            ),
            (
                "pl_costco",
                "Costco Wholesale",
                "supermarket",
                "1050 Cranberry Square Dr, Cranberry Twp, PA 16066",
                40.6865,
                -80.1065,
                "https://maps.google.com/?q=Costco+Cranberry",
                "ChIJ1yZ...Costco",
                "Bulk groceries, gas station, pharmacy.",
            ),
            (
                "pl_tj",
                "Trader Joe's",
                "supermarket",
                "8000 McKnight Rd, Pittsburgh, PA 15237",
                40.5489,
                -80.0152,
                "https://maps.google.com/?q=Trader+Joes+North+Hills",
                "ChIJ3bA...TJ",
                "Specialty snacks, flowers, produce.",
            ),
            (
                "pl_ge",
                "Giant Eagle Supermarket",
                "supermarket",
                "20675 Rte 19, Cranberry Twp, PA 16066",
                40.6961,
                -80.1098,
                "https://maps.google.com/?q=Giant+Eagle+Cranberry",
                "ChIJ2bC...GE",
                "Weekly fruit, deli, emergency groceries.",
            ),
            (
                "pl_valvoline",
                "Valvoline Instant Oil Change",
                "service",
                "20120 Rte 19, Cranberry Twp, PA 16066",
                40.6881,
                -80.1072,
                "https://maps.google.com/?q=Valvoline+Cranberry",
                "ChIJ4dD...Valvoline",
                "Drive-thru 15-minute oil change & tire rotation.",
            ),
            (
                "pl_oriental",
                "Oriental Market",
                "supermarket",
                "4768 McKnight Rd, Pittsburgh, PA 15237",
                40.5284,
                -80.0094,
                "https://maps.google.com/?q=Oriental+Market+Pittsburgh",
                "ChIJ...Oriental",
                "Asian grocery store: fresh produce, specialty snacks, sauces.",
            ),
            (
                "pl_home",
                "Home Base",
                "residence",
                "100 Main St, Cranberry Twp, PA 16066",
                40.6873,
                -80.1078,
                None,
                None,
                "Primary family home geofence center.",
            ),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO places 
            (id, name, category, address, latitude, longitude, map_url, google_place_id, notes) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            places_data,
        )

        # 3. Household Equipment (for Maintenance Foreign Keys)
        equipment_data = [
            ("eq_odyssey", "Honda Odyssey EX-L (2022)", "vehicle", "Odyssey EX-L", "1HGRB...2022", "2022-04-15", "2027-04-15", "Family road trip van."),
            ("eq_fridge", "Kitchen Refrigerator", "appliance", "Samsung RF28", "SN-981240", "2021-08-10", "2026-08-10", "Filter HAF-QIN required."),
            ("eq_hvac", "HVAC Lennox Furnace", "hvac", "EL296UH", "SN-542199", "2020-10-01", "2030-10-01", "Filter size 16x25x4."),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO household_equipment 
            (id, name, category, model_number, serial_number, purchase_date, warranty_expiry, notes) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            equipment_data,
        )

        # 4. Storage Locations & Quantity Units
        loc_data = [
            ("loc_fridge", "Kitchen Fridge", "Primary refrigerator"),
            ("loc_pantry", "Main Pantry", "Dry storage and canned goods"),
            ("loc_freezer", "Basement Chest Freezer", "Bulk meat and frozen items"),
            ("loc_bath", "Master Bath Closet", "Paper goods and hygiene"),
            ("loc_sink", "Kitchen Sink Cabinet", "Cleaning and dishwasher supplies"),
            ("loc_basket", "Fruit Basket", "Countertop fruit storage"),
        ]
        cursor.executemany("INSERT OR IGNORE INTO storage_locations (id, name, description) VALUES (?, ?, ?)", loc_data)

        unit_data = [
            ("ea", "each", "each"),
            ("pack", "pack", "packs"),
            ("roll", "roll", "rolls"),
            ("gal", "gallon", "gallons"),
            ("egg", "egg", "eggs"),
            ("pod", "pod", "pods"),
            ("lb", "pound", "pounds"),
            ("bunch", "bunch", "bunches"),
            ("cup", "cup", "cups"),
            ("case", "case", "cases"),
            ("tub", "tub", "tubs"),
            ("bag", "bag", "bags"),
            ("box", "box", "boxes"),
        ]
        cursor.executemany("INSERT OR IGNORE INTO quantity_units (id, name, name_plural) VALUES (?, ?, ?)", unit_data)

        # 5. Products with Costco Package Multiplier (qu_factor)
        products_data = [
            (
                "prod_tp",
                "Kirkland Bath Tissue (Toilet Paper)",
                "household",
                "loc_bath",
                "pl_costco",
                "pack",
                "roll",
                36.0,  # 1 pack = 36 rolls!
                1.0,
                "-1 Roll",
                1,  # is_fridge_quick_tile
                6.0,
                1.2,
                "Kirkland 2-ply bath tissue 36 rolls/pack",
            ),
            (
                "prod_milk",
                "Whole Milk",
                "dairy",
                "loc_fridge",
                "pl_costco",
                "pack",
                "gal",
                2.0,   # 1 twin pack = 2 gallons
                0.5,
                "-0.5 Gal",
                1,
                0.5,
                0.15,
                "Organic whole milk twin pack",
            ),
            (
                "prod_eggs",
                "Large Brown Eggs",
                "dairy",
                "loc_fridge",
                "pl_costco",
                "case",
                "egg",
                48.0,  # 1 case = 48 eggs
                2.0,
                "-2 Eggs",
                1,
                12.0,
                2.0,
                "Cage-free pasture raised brown eggs 2x24",
            ),
            (
                "prod_pt",
                "Kirkland Paper Towels",
                "household",
                "loc_pantry",
                "pl_costco",
                "pack",
                "roll",
                12.0,  # 1 pack = 12 rolls
                1.0,
                "-1 Roll",
                1,
                3.0,
                0.5,
                "Create-a-size paper towels",
            ),
            (
                "prod_pods",
                "Cascade Dishwasher Pods",
                "household",
                "loc_sink",
                "pl_costco",
                "tub",
                "pod",
                90.0,  # 1 tub = 90 pods
                1.0,
                "-1 Pod",
                1,
                10.0,
                1.0,
                "Cascade Platinum dishwasher action pacs",
            ),
            (
                "prod_banana",
                "Organic Bananas",
                "produce",
                "loc_basket",
                "pl_ge",
                "bunch",
                "ea",
                7.0,
                1.0,
                "-1 Banana",
                1,
                2.0,
                1.0,
                "Yellow organic bananas",
            ),
            (
                "prod_yogurt",
                "Greek Yogurt 3-Pack",
                "dairy",
                "loc_fridge",
                "pl_tj",
                "pack",
                "cup",
                3.0,
                1.0,
                "-1 Cup",
                1,
                1.0,
                0.25,
                "Trader Joe's organic plain Greek yogurt",
            ),
            (
                "prod_kiwi",
                "Kiwi Berries (1 lb)",
                "produce",
                "loc_fridge",
                "pl_costco",
                "pack",
                "lb",
                1.0,
                1.0,
                "-1 Pack",
                1,
                1.0,
                0.2,
                "Fresh organic kiwi berries",
            ),
            (
                "prod_pork_belly",
                "Kirkland Pork Belly",
                "meat",
                "loc_freezer",
                "pl_costco",
                "pack",
                "lb",
                1.0,
                1.0,
                "-1 lb",
                0,
                2.0,
                0.5,
                "Kirkland signature fresh pork belly",
            ),
            (
                "prod_chicken_wings",
                "Kirkland Seasoned Chicken Wings",
                "meat",
                "loc_fridge",
                "pl_costco",
                "pack",
                "ea",
                1.0,
                1.0,
                "-1 Pack",
                0,
                1.0,
                0.3,
                "Deli roasted & seasoned chicken party wings",
            ),
            (
                "prod_mandu",
                "CJ Bulgogi Mandu Dumplings",
                "frozen",
                "loc_freezer",
                "pl_costco",
                "bag",
                "ea",
                1.0,
                1.0,
                "-1 Bag",
                0,
                1.0,
                0.2,
                "CJ Bibigo Korean bulgogi beef mandu",
            ),
            (
                "prod_crunch_bon",
                "Haitai Crunch Bon Snack",
                "pantry",
                "loc_pantry",
                "pl_costco",
                "box",
                "ea",
                1.0,
                1.0,
                "-1 Box",
                0,
                1.0,
                0.2,
                "Haitai Crunch Bon crispy biscuit snacks",
            ),
            (
                "prod_cashews",
                "Kirkland Signature Whole Cashews",
                "pantry",
                "loc_pantry",
                "pl_costco",
                "tub",
                "ea",
                1.0,
                1.0,
                "-1 Tub",
                1,
                1.0,
                0.1,
                "Fancy whole cashews with sea salt 2.5 lb",
            ),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO products 
            (id, name, category, default_location_id, default_place_id, qu_purchase_id, qu_stock_id, 
             qu_factor, consume_step, consume_step_label, is_fridge_quick_tile, min_stock_amount, daily_burn_rate, notes) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            products_data,
        )

        # 6. Bulk Receipt Line-Item Conversions
        conversions_data = [
            ("conv_01", "prod_tp", "Costco", "KS BATH TISSUE 36/PK #1500", "pack", "rolls", 36.0),
            ("conv_02", "prod_milk", "Costco", "KS ORG WHOLE MILK 2/1GAL", "pack", "gal", 2.0),
            ("conv_03", "prod_eggs", "Costco", "KS ORG BROWN EGGS 2/24", "case", "eggs", 48.0),
            ("conv_04", "prod_pods", "Costco", "CASCADE PLAT 90CT TUB", "tub", "pods", 90.0),
            ("conv_05", "prod_pt", "Costco", "KS CREATE-A-SIZE 12/PK", "pack", "rolls", 12.0),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO product_unit_conversions 
            (id, product_id, store_name, receipt_raw_text, purchase_unit, stock_unit, unit_multiplier) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            conversions_data,
        )

        # 6.1 Multipliers & Product Linking Table: (store, item, multiplier, product_id)
        multipliers_data = [
            ("Costco", "KS BATH TISSUE 36/PK #1500", 36.0, "prod_tp"),
            ("Costco", "KS ORG WHOLE MILK 2/1GAL", 2.0, "prod_milk"),
            ("Costco", "ORG A2 WHOLE MILK 3-PK", 3.0, "prod_milk"),
            ("Costco", "KS ORG BROWN EGGS 2/24", 48.0, "prod_eggs"),
            ("Costco", "CASCADE PLAT 90CT TUB", 90.0, "prod_pods"),
            ("Costco", "KS CREATE-A-SIZE 12/PK", 12.0, "prod_pt"),
            ("Costco", "KS PAPER TOWELS", 12.0, "prod_pt"),
            ("Costco", "Kirkland Paper Towels", 12.0, "prod_pt"),
            ("Costco", "Kiwi Berries, 1 lb", 1.0, "prod_kiwi"),
            ("Costco", "KS KS PRK BELLY", 1.0, "prod_pork_belly"),
            ("Costco", "Kirkland Signature Seasoned Chicken Wings", 1.0, "prod_chicken_wings"),
            ("Costco", "CJ BULGOGI MANDU", 1.0, "prod_mandu"),
            ("Costco", "HAITAI CRUNCH BON", 1.0, "prod_crunch_bon"),
            ("Costco", "KS CASHEWS", 1.0, "prod_cashews"),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO item_multipliers (store, item, multiplier, product_id) 
            VALUES (?, ?, ?, ?)
            """,
            multipliers_data,
        )

        # 7. Initial Stock Balances
        stock_data = [
            ("stk_tp", "prod_tp", 14.0, "loc_bath", None, 23.99),
            ("stk_milk", "prod_milk", 1.2, "loc_fridge", None, 8.49),
            ("stk_eggs", "prod_eggs", 18.0, "loc_fridge", None, 9.99),
            ("stk_pt", "prod_pt", 2.0, "loc_pantry", None, 19.99),
            ("stk_pods", "prod_pods", 6.0, "loc_sink", None, 22.99),
            ("stk_banana", "prod_banana", 2.0, "loc_basket", None, 1.89),
            ("stk_yogurt", "prod_yogurt", 1.5, "loc_fridge", None, 4.99),
            ("stk_kiwi", "prod_kiwi", 1.0, "loc_fridge", None, 6.99),
            ("stk_pork", "prod_pork_belly", 5.2, "loc_freezer", None, 19.99),
            ("stk_wings", "prod_chicken_wings", 1.0, "loc_fridge", None, 14.99),
            ("stk_mandu", "prod_mandu", 2.0, "loc_freezer", None, 12.99),
            ("stk_crunch", "prod_crunch_bon", 3.0, "loc_pantry", None, 8.99),
            ("stk_cashews", "prod_cashews", 1.0, "loc_pantry", None, 15.99),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO stock (id, product_id, amount, location_id, purchased_event_id, price) VALUES (?, ?, ?, ?, ?, ?)",
            stock_data,
        )

        # 8. Pending Depletion Proposals at Confirmation Gate
        depletions_data = [
            ("dep_01", "prod_milk", 0.5, "gal", "Estimated daily toddler milk consumption (Marcus)", 0.92, "PENDING"),
            ("dep_02", "prod_eggs", 6.0, "eggs", "Weekend family breakfast recipe", 0.88, "PENDING"),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO depletion_proposals 
            (id, product_id, proposed_amount, unit, reason, confidence_score, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            depletions_data,
        )

        # 9. Initial Life Events & Polymorphic Joined Details (Using Approach 2)
        events_data = [
            # 9.1 Completed Dining Event
            (
                "evt_dining_01",
                "Dinner at Mad Mex",
                "DINING",
                "2026-11-08 18:30:00",
                "2026-11-08 19:45:00",
                None,  # deadline
                "2026-11-08 19:45:00",
                0,
                "pl_madmex",
                json.dumps(["Dad", "Mom", "Marcus"]),
                4.10,
                "Family dinner, good tacos.",
                "RECEIPT_OCR",
                "sha_madmex_sample",
                0,
                None,
                None,
            ),
            # 9.2 Completed Maintenance Event
            (
                "evt_maint_01",
                "Honda Odyssey Oil Change",
                "MAINTENANCE",
                "2026-11-05 10:00:00",
                "2026-11-05 10:45:00",
                None,  # deadline
                "2026-11-05 10:45:00",
                0,
                "pl_valvoline",
                json.dumps(["Dad"]),
                6.30,
                "Full synthetic oil change & tire rotation.",
                "RECEIPT_OCR",
                "sha_valvoline_sample",
                0,
                None,
                None,
            ),
            # 9.3 Upcoming Kid Activity Event (with Mutex Conflict at YMCA!)
            (
                "evt_swim_01",
                "Marcus Warm Pool Swimming Lesson",
                "KID_ACTIVITY",
                "2026-11-09 16:00:00",
                "2026-11-09 16:45:00",
                "2026-11-09 16:00:00",  # deadline matches lesson time
                None,  # Upcoming task!
                0,
                "pl_ymca",
                json.dumps(["Dad", "Marcus"]),
                0.0,
                "Warm Water Pool swim lesson with Coach Sarah.",
                "QUICK_PRESET",
                "tpl_swim",
                1,  # has_conflict
                "DETECTED",
                "Warm Water Pool occupied by Aqua Aerobics until 5:00 PM",
            ),
            # 9.4 Upcoming Financial Task with Hard Deadline (Close to deadline!)
            (
                "evt_tax_01",
                "County Property Tax Due (Discount Period)",
                "CUSTOM",
                "2026-11-10 09:00:00",
                "2026-11-10 09:30:00",
                "2026-11-15 23:59:59",  # Hard deadline: Nov 15!
                None,  # Upcoming task!
                0,
                "pl_home",
                json.dumps(["Dad"]),
                0.0,
                "Pay 2% discount rate via Cranberry Tax Collector portal.",
                "EVENT_GENERATOR",
                "gen_tax",
                0,
                None,
                None,
            ),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO events 
            (id, title, event_type, scheduled_at, scheduled_end_at, deadline, completed_at, all_day, place_id, 
             people_involved, tax_amount, notes, source, source_reference_id, 
             has_conflict, conflict_status, conflict_reason) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            events_data,
        )

        # 9.4 Polymorphic Joined Tables (Approach 2)
        # Dining Detail (event_type = 'DINING')
        cursor.execute(
            """
            INSERT OR IGNORE INTO dining_details (event_id, event_type, rating, total_amount) 
            VALUES (?, 'DINING', ?, ?)
            """,
            ("evt_dining_01", 5, 58.50),
        )

        # Maintenance Detail (event_type = 'MAINTENANCE')
        cursor.execute(
            """
            INSERT OR IGNORE INTO maintenance_details (event_id, event_type, equipment_id, service_type, next_due_interval_days, next_due_miles) 
            VALUES (?, 'MAINTENANCE', ?, ?, ?, ?)
            """,
            ("evt_maint_01", "eq_odyssey", "oil_change", 180, 5000),
        )


        # 9.5 Event Generators (Annual / Recurring Rules with Deadlines)
        generators_data = [
            (
                "gen_tax",
                "Annual County Property Tax Payment",
                "CUSTOM",
                "YEARLY",
                1,
                11,
                15,
                None,
                "2026-11-15",
                30,
                1,  # has_deadline
                0,  # deadline_offset_days (Nov 15 is the deadline!)
                "23:59:59",
                "pl_home",
                30,
                json.dumps(["Dad"]),
                2840.50,
                "Pay 2% discount rate via Cranberry Tax Collector portal.",
                1,
            ),
            (
                "gen_inspection",
                "Honda Odyssey State Inspection & Emissions",
                "MAINTENANCE",
                "YEARLY",
                1,
                5,
                31,
                None,
                "2027-05-31",
                30,
                1,  # has_deadline
                0,
                "17:00:00",
                "pl_valvoline",
                60,
                json.dumps(["Dad"]),
                95.00,
                "PA State Safety & Emissions inspection sticker renewal.",
                1,
            ),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO event_generators 
            (id, title, event_type, frequency, interval, by_month, by_month_day, by_weekday, 
             anchor_date, lead_time_days, has_deadline, deadline_offset_days, deadline_time, 
             place_id, duration_minutes, people_involved, estimated_amount, notes, is_active) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            generators_data,
        )

        # 10. Vacation Trips (Inverted Geofence)
        cursor.execute(
            """
            INSERT OR IGNORE INTO trips 
            (id, name, start_date, end_date, budget, spent, geofence_center_lat, geofence_center_lng, inverted_geofence_radius_miles, notes) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trip_disney_2026",
                "Disney World Family Road Trip",
                "2026-11-18",
                "2026-11-25",
                3500.0,
                1420.0,
                40.6873,
                -80.1078,
                30.0,
                "Annual family Thanksgiving road trip in the Honda Odyssey.",
            ),
        )

        trip_stops_data = [
            ("stop_01", "trip_disney_2026", "Buc-ee's Florence, SC (Fuel & Snacks)", "2026-11-18", "Fuel", 68.40, "Snacks and fuel stop", 1),
            ("stop_02", "trip_disney_2026", "Disney Coronado Springs Resort", "2026-11-19", "Lodging", 1150.00, "Hotel stay 5 nights", 2),
        ]
        cursor.executemany(
            """
            INSERT OR IGNORE INTO trip_stops (id, trip_id, name, stop_date, category, spent, notes, order_index) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trip_stops_data,
        )

        logger.info("Database successfully seeded with realistic LiftAssistant 3.0 baseline data.")
