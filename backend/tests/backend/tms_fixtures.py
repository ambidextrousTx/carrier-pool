# Fixtures transcribed directly from the sync files
# (comments removed, values unchanged) so adapter tests run against real
# data rather than invented approximations of it.

# --- FreightFlow: 06:00 sync, load not yet booked ---------------------------
FREIGHTFLOW_SYNC_UNBOOKED = {
    "syncedAt": "2026-07-06T06:00:00-05:00",
    "loads": [
        {
            "shipmentId": 127472397,
            "status": "Booking",
            "mileage": 242.1,
            "totalSell": 1450.0,
            "totalBuy": None,
            "customer": {"customerId": 889264, "name": "Lone Star Beverages"},
            "carrier": None,
            "equipment": "53 ft Van | Dry",
            "weightTotal": 24000.0,
            "stops": [
                {
                    "stopType": "First Pickup",
                    "city": "GRAND PRAIRIE",
                    "state": "TX",
                    "zipCode": "75050",
                    "estimatedReadyDateTime": "2026-07-07T08:00:00-05:00",
                    "estimatedCloseDateTime": "2026-07-07T16:00:00-05:00",
                    "actualDepartureDateTime": None,
                },
                {
                    "stopType": "Last Drop",
                    "city": "KATY",
                    "state": "TX",
                    "zipCode": "77449",
                    "estimatedReadyDateTime": "2026-07-08T08:00:00-05:00",
                    "estimatedCloseDateTime": "2026-07-08T16:00:00-05:00",
                    "actualDepartureDateTime": None,
                },
            ],
            "createdDate": "2026-07-06T04:12:44-05:00",
            "lastModifiedDate": "2026-07-06T04:12:44-05:00",
        }
    ],
}

# --- FreightFlow: 12:00 sync, same load, now booked --------------------------
FREIGHTFLOW_SYNC_BOOKED = {
    "syncedAt": "2026-07-06T12:00:00-05:00",
    "loads": [
        {
            "shipmentId": 127472397,
            "status": "Dispatched",
            "mileage": 242.1,
            "totalSell": 1450.0,
            "totalBuy": 1180.0,
            "customer": {"customerId": 889264, "name": "Lone Star Beverages"},
            "carrier": {
                "carrierMasterId": 835692,
                "name": "IBRAHIM TRANSPORT INC",
                "mcNumber": "1346382",
                "dotNumber": "3771394",
                "phoneNumber": "+15714906959",
            },
            "equipment": "53 ft Van | Dry",
            "weightTotal": 24000.0,
            "stops": [
                {
                    "stopType": "First Pickup",
                    "city": "GRAND PRAIRIE",
                    "state": "TX",
                    "zipCode": "75050",
                    "estimatedReadyDateTime": "2026-07-07T08:00:00-05:00",
                    "estimatedCloseDateTime": "2026-07-07T16:00:00-05:00",
                    "actualDepartureDateTime": None,
                },
                {
                    "stopType": "Last Drop",
                    "city": "KATY",
                    "state": "TX",
                    "zipCode": "77449",
                    "estimatedReadyDateTime": "2026-07-08T08:00:00-05:00",
                    "estimatedCloseDateTime": "2026-07-08T16:00:00-05:00",
                    "actualDepartureDateTime": None,
                },
            ],
            "createdDate": "2026-07-06T04:12:44-05:00",
            "lastModifiedDate": "2026-07-06T10:03:17-05:00",
        }
    ],
}

# --- HaulDesk: 06:00 sync ----------------------------------------------------
HAULDESK_SYNC = {
    "synced_at": "2026-07-06 06:00:00",
    "loads": [
        {
            "load_num": "HD-2026-004417",
            "status_code": 30,
            "customer_code": "C-0031",
            "customer_name": "Alamo Building Supply",
            "carrier_ref": 66861,
            "equip": "V",
            "weight_kg": 10886.2,
            "dist_km": 389.6,
            "pu_city": "New Braunfels",
            "pu_state": "TX",
            "pu_zip": "78130",
            "pu_date": "2026-07-07",
            "pu_departed_at": None,
            "del_city": "Pasadena",
            "del_state": "TX",
            "del_zip": "77502",
            "del_date": "2026-07-08",
            "del_arrived_at": None,
            "entered_at": "2026-07-05 14:22:10",
            "updated_at": "2026-07-06 03:45:33",
        }
    ],
    "carriers": [
        {
            "carrier_id": 66861,
            "carrier_name": "DELTA PRIME LLC",
            "mc_no": "884201",
            "dot_no": "2551377",
            "home_city": "Seguin",
            "home_state": "TX",
            "phone": "(830) 555-0144",
        }
    ],
    "rates": [
        {
            "rate_id": 910233,
            "load_num": "HD-2026-004417",
            "side": "pay",
            "code": "LINEHAUL",
            "amount_usd": 1035.00,
            "created_at": "2026-07-06 03:45:33",
        },
        {
            "rate_id": 910234,
            "load_num": "HD-2026-004417",
            "side": "bill",
            "code": "LINEHAUL",
            "amount_usd": 1310.00,
            "created_at": "2026-07-06 03:45:33",
        },
    ],
}

# --- BrokerOS: 06:00 sync ----------------------------------------------------
BROKEROS_SYNC = {
    "synced_at": "2026-07-06T11:00:00.000+0000",
    "records": [
        {
            "Id": "a0jO900000YgsYJIAZ",
            "Name": "SHP6743062",
            "bos__Load_Status__c": "Ready to Book",
            "bos__Distance_Miles__c": 197.4,
            "bos__Customer__c": "0011I00000NMUrPQAX",
            "bos__Carrier__c": None,
            "bos__Equipment_Type__c": "Reefer",
            "bos__Customer_Rate__c": 1720.00,
            "bos__Carrier_Rate__c": None,
            "bos__Stops__r": [
                {
                    "bos__Number__c": 1.0,
                    "bos__Is_Pickup__c": True,
                    "bos__Is_Dropoff__c": False,
                    "bos__Location__c": "0011I00000HAeJnQAL",
                    "bos__Scheduled_Date__c": "2026-07-07",
                    "bos__Arrival_Time__c": None,
                },
                {
                    "bos__Number__c": 2.0,
                    "bos__Is_Pickup__c": False,
                    "bos__Is_Dropoff__c": True,
                    "bos__Location__c": "0011I00000NMha6QAD",
                    "bos__Scheduled_Date__c": "2026-07-08",
                    "bos__Arrival_Time__c": None,
                },
            ],
            "bos__Line_Items__r": [
                {
                    "bos__Commodity__c": "Packaged foods",
                    "bos__Weight__c": 14440.0,
                    "bos__Weight_Units__c": "lbs",
                    "bos__Pallet_Count__c": 18.0,
                }
            ],
            "CreatedDate": "2026-07-06T09:40:02.000+0000",
            "LastModifiedDate": "2026-07-06T09:40:02.000+0000",
        }
    ],
    "referenced_records": {
        "0011I00000HAeJnQAL": {
            "type": "Location",
            "Name": "Sugar Land Cold Storage",
            "bos__City__c": "Sugar Land",
            "bos__State__c": "TX",
            "bos__Postal_Code__c": "77478",
        },
        "0011I00000NMha6QAD": {
            "type": "Location",
            "Name": "Schertz Distribution Ctr",
            "bos__City__c": "Schertz",
            "bos__State__c": "TX",
            "bos__Postal_Code__c": "78154",
        },
        "0011I00000NMUrPQAX": {
            "type": "Account",
            "record_type": "Customer",
            "Name": "Gulf Coast Foods",
        },
    },
}
