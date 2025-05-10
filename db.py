from web3 import Web3
import json
import os
from dotenv import load_dotenv
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
import pytz
from web3.gas_strategies.time_based import medium_gas_price_strategy
import time  # Added missing import

# --------------------------------------------------
# 🔹 Load Environment Variables
# --------------------------------------------------
load_dotenv()
WEB3_PROVIDER_URI = os.getenv("WEB3_PROVIDER_URI")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ADDRESS = os.getenv("OWNER_ADDRESS")  # For owner-only functions

# --------------------------------------------------
# 🔹 MongoDB Setup
# --------------------------------------------------
client = MongoClient(MONGO_URI)
db = client["AnnSuraksha"]

# Collections
users_collection = db["users"]
complaints_collection = db["complaints"]
deliveries_collection = db["deliveries"]
fps_collection = db["fps"]
items_collection = db["items"]
orders_collection = db["orders"]
trust_scores_collection = db["trust_scores"]
order_tracking_collection = db["order_tracking"]
nearby_shops_collection = db["nearby_shops"]
inventory_collection = db["inventory"]
reviews_collection = db["reviews"]
user_sessions_collection = db["user_sessions"]
blockchain_logs_collection = db["blockchain_logs"]

# --------------------------------------------------
# 🔹 Connect to Blockchain
# --------------------------------------------------
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URI))
w3.eth.set_gas_price_strategy(medium_gas_price_strategy)

contract_address = Web3.to_checksum_address(CONTRACT_ADDRESS)
account_address = Web3.to_checksum_address(ACCOUNT_ADDRESS)
owner_address = Web3.to_checksum_address(ACCOUNT_ADDRESS)

# Load ABI
with open('AnnSurakshaABI.json', 'r') as abi_file:
    abi_data = json.load(abi_file)
    abi = abi_data["data"] if "data" in abi_data else abi_data

contract = w3.eth.contract(address=contract_address, abi=abi)

# --------------------------------------------------
# 🔹 Blockchain Mappings
# --------------------------------------------------
STATUS_MAPPING = {
    0: "Pending",
    1: "Delivered",
    2: "Disputed",
    3: "Resolved"
}

# --------------------------------------------------
# 🔹 Enhanced Blockchain Utilities
# --------------------------------------------------
def send_transaction(txn_builder, sender_address, private_key):
    """Helper function to send transactions with proper gas estimation"""
    nonce = w3.eth.get_transaction_count(sender_address)
    
    txn = txn_builder.build_transaction({
        'from': sender_address,
        'nonce': nonce,
        'gas': 500000  # Will be adjusted by estimate_gas
    })
    
    # Estimate gas and adjust gas price
    txn['gas'] = w3.eth.estimate_gas(txn)
    txn['gasPrice'] = w3.eth.generate_gas_price()
    
    signed_txn = w3.eth.account.sign_transaction(txn, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    return w3.to_hex(tx_hash)

# --------------------------------------------------
# 🔹 CRUD Operations
# --------------------------------------------------
def insert_document(collection, data: dict):
    """Inserts a document into a specified collection."""
    try:
        result = collection.insert_one(data)
        print(f"✅ Document inserted with ID: {result.inserted_id}")
        return result
    except Exception as e:
        print(f"❌ Error inserting document: {e}")
        return None

def update_document(collection, query: dict, update_data: dict):
    """Updates documents matching the query."""
    try:
        result = collection.update_one(query, {"$set": update_data})
        if result.modified_count > 0:
            print(f"✅ Document updated")
        else:
            print(f"⚠️ No documents matched the query")
        return result
    except Exception as e:
        print(f"❌ Error updating document: {e}")
        return None

def find_documents(collection, query: dict = {}):
    """Finds documents based on a query. Returns a list of documents."""
    try:
        return list(collection.find(query))
    except Exception as e:
        print(f"❌ Error finding documents: {e}")
        return []

# --------------------------------------------------
# 🔹 Integrated Blockchain + MongoDB Operations
# --------------------------------------------------
def log_delivery(beneficiary, fps_code, location, amount, ipfs_hash, user_id=None, items=None):
    """Logs a delivery on blockchain and MongoDB with full integration"""
    try:
        # Blockchain transaction
        txn_builder = contract.functions.logDelivery(
            Web3.to_checksum_address(beneficiary),
            Web3.to_bytes(text=fps_code),
            Web3.to_bytes(text=location),
            amount,
            ipfs_hash
        )
        tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
        
        # Get delivery ID from blockchain
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = contract.events.DeliveryLogged().process_receipt(receipt)
        delivery_id = logs[0]['args']['deliveryId'] if logs else None
        
        if delivery_id is None:
            delivery_id = contract.functions.nextDeliveryId().call() - 1
        
        # MongoDB document
        delivery_data = {
            "blockchain_delivery_id": delivery_id,
            "user_id": ObjectId(user_id) if user_id else None,
            "beneficiary": beneficiary,
            "fps_code": fps_code,
            "location": location,
            "amount": amount,
            "items": items or [],
            "ipfs_hash": ipfs_hash,
            "delivery_time": datetime.now(pytz.UTC),
            "status": "Pending",
            "tx_hash": tx_hash
        }
        insert_document(deliveries_collection, delivery_data)
        
        # Update FPS shop stats
        update_fps_stats(fps_code)
        
        print(f"✅ Delivery Logged with Blockchain ID: {delivery_id}")
        return tx_hash, delivery_id
        
    except Exception as e:
        print(f"❌ Error logging delivery: {str(e)}")
        raise

def confirm_delivery(mongo_delivery_id):
    """Confirms delivery on blockchain and updates MongoDB"""
    try:
        delivery = deliveries_collection.find_one({"_id": ObjectId(mongo_delivery_id)})
        if not delivery:
            raise Exception(f"Delivery ID {mongo_delivery_id} not found")
        
        delivery_id = delivery["blockchain_delivery_id"]
        
        # Blockchain transaction
        txn_builder = contract.functions.confirmDelivery(delivery_id)
        tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
        
        # Update MongoDB
        update_data = {
            "status": "Delivered",
            "confirmation_tx_hash": tx_hash,
            "collection_time": datetime.now(pytz.UTC)
        }
        update_document(
            deliveries_collection,
            {"_id": ObjectId(mongo_delivery_id)},
            update_data
        )
        
        # Update user trust score
        if delivery.get("user_id"):
            update_trust_score(delivery["user_id"], positive=True)
        
        print(f"✅ Delivery ID {delivery_id} confirmed on blockchain.")
        return tx_hash
        
    except Exception as e:
        print(f"❌ Error confirming delivery: {str(e)}")
        raise

def file_complaint(mongo_delivery_id, complaint_details, user_id=None):
    """Files a complaint on blockchain and updates MongoDB"""
    try:
        delivery = deliveries_collection.find_one({"_id": ObjectId(mongo_delivery_id)})
        if not delivery:
            raise Exception(f"Delivery ID {mongo_delivery_id} not found")
        
        delivery_id = delivery["blockchain_delivery_id"]
        
        # Blockchain transaction
        txn_builder = contract.functions.fileComplaint(delivery_id, complaint_details)
        tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
        
        # Update MongoDB delivery status
        update_document(
            deliveries_collection,
            {"_id": ObjectId(mongo_delivery_id)},
            {"status": "Disputed", "dispute_tx_hash": tx_hash}
        )
        
        # Create complaint record
        complaint_data = {
            "delivery_id": ObjectId(mongo_delivery_id),
            "blockchain_delivery_id": delivery_id,
            "user_id": ObjectId(user_id) if user_id else None,
            "complaint_details": complaint_details,
            "status": "Pending",
            "timestamp": datetime.now(pytz.UTC),
            "tx_hash": tx_hash
        }
        insert_document(complaints_collection, complaint_data)
        
        print(f"⚠️ Complaint filed for Delivery ID {delivery_id}.")
        return tx_hash
        
    except Exception as e:
        print(f"❌ Error filing complaint: {str(e)}")
        raise

# --------------------------------------------------
# 🔹 Additional Integrated Functions
# --------------------------------------------------
def update_fps_stats(fps_code):
    """Updates statistics for an FPS shop after delivery"""
    fps = fps_collection.find_one({"fps_code": fps_code})
    if fps:
        new_count = fps.get("delivery_count", 0) + 1
        update_document(
            fps_collection,
            {"_id": fps["_id"]},
            {"delivery_count": new_count, "last_delivery": datetime.now(pytz.UTC)}
        )

def update_trust_score(user_id, positive=True):
    """Updates user trust score based on delivery outcome"""
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        current_score = user.get("trust_score", 100)
        new_score = current_score + (5 if positive else -10)
        new_score = max(0, min(100, new_score))  # Keep between 0-100
        
        update_document(
            users_collection,
            {"_id": ObjectId(user_id)},
            {"trust_score": new_score}
        )
        
        # Record in trust_scores collection
        insert_document(
            trust_scores_collection,
            {
                "user_id": ObjectId(user_id),
                "score": new_score,
                "change": new_score - current_score,
                "timestamp": datetime.now(pytz.UTC),
                "reason": "Delivery confirmed" if positive else "Complaint filed"
            }
        )

# --------------------------------------------------
# 🔹 Admin Functions
# --------------------------------------------------
def resolve_dispute(mongo_delivery_id, resolution, dealer_at_fault=False):
    """Admin function to resolve disputes on blockchain and MongoDB"""
    try:
        delivery = deliveries_collection.find_one({"_id": ObjectId(mongo_delivery_id)})
        if not delivery:
            raise Exception(f"Delivery ID {mongo_delivery_id} not found")
        
        delivery_id = delivery["blockchain_delivery_id"]
        
        # Blockchain transaction
        txn_builder = contract.functions.resolveDispute(delivery_id, dealer_at_fault)
        tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
        
        # Update MongoDB delivery status
        update_document(
            deliveries_collection,
            {"_id": ObjectId(mongo_delivery_id)},
            {"status": "Resolved", "resolution_tx_hash": tx_hash}
        )
        
        # Update complaint status
        complaint = complaints_collection.find_one({"delivery_id": ObjectId(mongo_delivery_id)})
        if complaint:
            update_document(
                complaints_collection,
                {"_id": complaint["_id"]},
                {
                    "status": "Resolved",
                    "resolution": resolution,
                    "dealer_at_fault": dealer_at_fault,
                    "resolution_time": datetime.now(pytz.UTC)
                }
            )
        
        # Update dealer reputation if at fault
        if dealer_at_fault:
            dealer_address = contract.functions.deliveries(delivery_id).call()[0]
            update_document(
                users_collection,
                {"wallet_address": dealer_address},
                {"$inc": {"reputation_score": -1}}
            )
        
        print(f"✅ Dispute resolved for Delivery ID {delivery_id}.")
        return tx_hash
        
    except Exception as e:
        print(f"❌ Error resolving dispute: {str(e)}")
        raise

# --------------------------------------------------
# 🔹 Query Functions
# --------------------------------------------------
def get_user_deliveries(user_id):
    """Get all deliveries for a user with blockchain verification"""
    mongo_deliveries = find_documents(deliveries_collection, {"user_id": ObjectId(user_id)})
    
    verified_deliveries = []
    for delivery in mongo_deliveries:
        if "blockchain_delivery_id" in delivery:
            blockchain_data = contract.functions.deliveries(delivery["blockchain_delivery_id"]).call()
            verified_delivery = {
                **delivery,
                "blockchain_status": STATUS_MAPPING.get(blockchain_data[7], "Unknown"),
                "verified": True
            }
            verified_deliveries.append(verified_delivery)
    
    return verified_deliveries

def get_delivery_details(delivery_id, from_blockchain=False):
    """Get delivery details from MongoDB or blockchain"""
    if from_blockchain:
        delivery = contract.functions.deliveries(delivery_id).call()
        return {
            "dealer": delivery[0],
            "beneficiary": delivery[1],
            "status": STATUS_MAPPING.get(delivery[7], "Unknown"),
            "amount": delivery[4],
            "delivery_time": datetime.fromtimestamp(delivery[5]),
            "collection_time": datetime.fromtimestamp(delivery[6]) if delivery[6] > 0 else None
        }
    else:
        return deliveries_collection.find_one({"blockchain_delivery_id": delivery_id})

# --------------------------------------------------
# 🔹 Initialization Check
# --------------------------------------------------
print("✅ MongoDB connected successfully!")
print(f"Available collections: {db.list_collection_names()}")
print(f"✅ Blockchain connected: {w3.is_connected()}")
print(f"Contract address: {contract_address}")