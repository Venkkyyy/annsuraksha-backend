from web3 import Web3
import json
import os
from dotenv import load_dotenv
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId
import pytz
from web3.gas_strategies.time_based import medium_gas_price_strategy
import requests

PINATA_API_KEY = '9df66d5fbba409a52eef'
PINATA_SECRET_API_KEY = '58c07298bffc57e2143672484f6d66bee12661c69e874e486880f66d93ca05d1'

def upload_to_pinata(file_path):
    url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    headers = {
        "pinata_api_key": PINATA_API_KEY,
        "pinata_secret_api_key": PINATA_SECRET_API_KEY
    }
    
    with open(file_path, 'rb') as file:
        files = {
            'file': (file_path, file)
        }
        response = requests.post(url, files=files, headers=headers)
        
        if response.status_code == 200:
            print("File successfully uploaded to Pinata!")
            ipfs_hash = response.json()['IpfsHash']
            print(f"IPFS Hash: {ipfs_hash}")
            print(f"IPFS URL: https://gateway.pinata.cloud/ipfs/{ipfs_hash}")
            return ipfs_hash
        else:
            print("Failed to upload to Pinata:", response.text)
            return None

upload_to_pinata('D:/file.txt')

# --------------------------------------------------
# 🔹 Load Environment Variables
# --------------------------------------------------
load_dotenv()
WEB3_PROVIDER_URI = os.getenv("WEB3_PROVIDER_URI")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
MONGO_URI = os.getenv("MONGO_URI")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")  # For owner-only functions

# --------------------------------------------------
# 🔹 MongoDB Setup (Moved to top)
# --------------------------------------------------
client = MongoClient(MONGO_URI)
db = client['AnnSuraksha']
deliveries_collection = db['deliveries']
complaints_collection = db['complaints']

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
# 🔹 Complete Contract Function Implementations
# --------------------------------------------------

def authorize_dealer(dealer_address, is_authorized):
    """Authorize/unauthorize a dealer (owner only)"""
    if account_address.lower() != owner_address.lower():
        raise Exception("Only contract owner can authorize dealers")
    
    txn_builder = contract.functions.setDealerAuthorization(
        Web3.to_checksum_address(dealer_address),
        is_authorized
    )
    tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
    return tx_hash

def resolve_dispute(delivery_id, dealer_at_fault):
    """Resolve a disputed delivery (owner only)"""
    if account_address.lower() != owner_address.lower():
        raise Exception("Only contract owner can resolve disputes")
    
    txn_builder = contract.functions.resolveDispute(
        delivery_id,
        dealer_at_fault
    )
    tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
    
    # Update MongoDB
    deliveries_collection.update_one(
        {"blockchain_delivery_id": delivery_id},
        {"$set": {"status": "Resolved"}}
    )
    complaints_collection.update_one(
        {"delivery_id": delivery_id},
        {"$set": {"status": "Resolved", "resolution": dealer_at_fault}}
    )
    return tx_hash

# [Rest of your functions remain the same...]

def create_proposal(target_address, payload, description):
    """Create a new governance proposal (owner only)"""
    if account_address.lower() != owner_address.lower():
        raise Exception("Only contract owner can create proposals")
    
    # Convert address and payload to bytes if needed
    target = Web3.to_checksum_address(target_address)
    if isinstance(payload, str):
        payload = Web3.to_bytes(text=payload)
    
    txn_builder = contract.functions.createProposal(
        target,
        payload,
        description
    )
    tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
    return tx_hash

def cast_vote(proposal_id, support):
    """Cast a vote on a proposal"""
    txn_builder = contract.functions.castVote(
        proposal_id,
        support
    )
    tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
    return tx_hash

def execute_proposal(proposal_id):
    """Execute a passed proposal"""
    txn_builder = contract.functions.executeProposal(
        proposal_id
    )
    tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
    return tx_hash

# --------------------------------------------------
# 🔹 Enhanced Existing Functions
# --------------------------------------------------

def log_delivery(beneficiary, fps_code, location, amount, ipfs_hash):
    """Enhanced delivery logging with better error handling"""
    try:
        txn_builder = contract.functions.logDelivery(
            Web3.to_checksum_address(beneficiary),
            Web3.to_bytes(text=fps_code),
            Web3.to_bytes(text=location),
            amount,
            ipfs_hash
        )
        
        tx_hash = send_transaction(txn_builder, account_address, PRIVATE_KEY)
        
        # Get delivery ID from emitted event (more reliable than counting)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = contract.events.DeliveryLogged().process_receipt(receipt)
        delivery_id = logs[0]['args']['deliveryId'] if logs else None
        
        if delivery_id is None:
            delivery_id = contract.functions.nextDeliveryId().call() - 1
        
        # MongoDB Insert
        delivery_data = {
            "blockchain_delivery_id": delivery_id,
            "beneficiary": beneficiary,
            "fps_code": fps_code,
            "location": location,
            "amount": amount,
            "ipfs_hash": ipfs_hash,
            "delivery_time": datetime.now(pytz.UTC),
            "status": "Pending",
            "tx_hash": tx_hash
        }
        deliveries_collection.insert_one(delivery_data)
        
        print(f"✅ Delivery Logged with Blockchain ID: {delivery_id}")
        return tx_hash
        
    except Exception as e:
        print(f"❌ Error logging delivery: {str(e)}")
        raise

# --------------------------------------------------
# 🔹 Query Functions
# --------------------------------------------------

def get_delivery_status(delivery_id):
    """Get delivery status from blockchain"""
    delivery = contract.functions.deliveries(delivery_id).call()
    return {
        "status": STATUS_MAPPING.get(delivery[7], "Unknown"),  # status is at index 7
        "beneficiary": delivery[1],
        "dealer": delivery[0],
        "amount": delivery[4],
        "delivery_time": datetime.fromtimestamp(delivery[5]),
        "collection_time": datetime.fromtimestamp(delivery[6]) if delivery[6] > 0 else None
    }

def get_dealer_reputation(dealer_address):
    """Get dealer reputation score"""
    return contract.functions.dealerReputation(
        Web3.to_checksum_address(dealer_address)
    ).call()

def get_proposal_details(proposal_id):
    """Get full proposal details"""
    proposal = contract.functions.proposals(proposal_id).call()
    return {
        "description": proposal[2],
        "vote_end": datetime.fromtimestamp(proposal[3]),
        "for_votes": proposal[4],
        "against_votes": proposal[5],
        "executed": proposal[6]
    }