# Updated data.py with complete dashboard integration
from faker import Faker
from pymongo import MongoClient
from datetime import datetime, timedelta
import random
import hashlib
from bson.objectid import ObjectId
import pytz
from web3 import Web3
import json
from dotenv import load_dotenv
import os
import time

# Initialize Faker with Indian locale
fake = Faker('en_IN')

# --------------------------------------------------
# 🔹 Load Environment Variables (matches db.py)
# --------------------------------------------------
load_dotenv()
WEB3_PROVIDER_URI = os.getenv("WEB3_PROVIDER_URI")
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS")
MONGO_URI = os.getenv("MONGO_URI")

# --------------------------------------------------
# 🔹 MongoDB Setup (matches db.py)
# --------------------------------------------------
client = MongoClient(MONGO_URI)
db = client["AnnSuraksha"]

# Collections (aligned with dashboard requirements)
collections = {
    'users': db['users'],
    'complaints': db['complaints'],
    'deliveries': db['deliveries'],
    'fps': db['fps'],
    'trust_scores': db['trust_scores'],
    'blockchain_logs': db['blockchain_logs'],
    'dashboard_metrics': db['dashboard_metrics']  # New collection for dashboard
}

# --------------------------------------------------
# 🔹 Helper Functions
# --------------------------------------------------
def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_fake_fps(num_fps: int):
    """Generate FPS shops with dealers"""
    dealers = list(collections['users'].find({'role': 'dealer'}))
    if not dealers:
        # Create some dealers if none exist
        generate_realistic_users(5)
        dealers = list(collections['users'].find({'role': 'dealer'}))
    
    fps_shops = []
    for _ in range(num_fps):
        dealer = random.choice(dealers)
        fps = {
            'fps_code': f"FPS{fake.unique.random_number(digits=6)}",
            'name': fake.company(),
            'dealer_id': dealer['_id'],
            'dealer_name': dealer['name'],
            'dealer_wallet': dealer['wallet_address'],
            'location': {
                'coordinates': [float(fake.longitude()), float(fake.latitude())],
                'address': fake.address(),
                'city': random.choice(['Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Chennai']),
                'state': random.choice(['Maharashtra', 'Karnataka', 'Tamil Nadu', 'Uttar Pradesh'])
            },
            'inventory': [
                {'item': 'Rice', 'stock': random.randint(100, 500), 'unit': 'kg'},
                {'item': 'Wheat', 'stock': random.randint(100, 500), 'unit': 'kg'},
                {'item': 'Sugar', 'stock': random.randint(50, 200), 'unit': 'kg'},
                {'item': 'Kerosene', 'stock': random.randint(50, 200), 'unit': 'liters'}
            ],
            'created_at': datetime.now(pytz.UTC) - timedelta(days=random.randint(1, 365)),
            'delivery_count': 0
        }
        fps_shops.append(fps)
    
    result = collections['fps'].insert_many(fps_shops)
    print(f"✅ Generated {len(result.inserted_ids)} FPS shops")
    return result.inserted_ids

# --------------------------------------------------
# 🔹 Enhanced Data Generators
# --------------------------------------------------
def generate_realistic_users(num_users: int):
    """Generate users with realistic Indian names and proper roles"""
    roles_distribution = {
        'beneficiary': 0.7,
        'dealer': 0.25,
        'admin': 0.05
    }
    
    users = []
    for i in range(num_users):
        # Determine role based on distribution
        rand = random.random()
        role = 'admin' if i == 0 else \
               'dealer' if rand < roles_distribution['dealer'] else \
               'admin' if rand < roles_distribution['admin'] else 'beneficiary'
        
        # Generate realistic Indian name
        name = fake.name()
        
        user = {
            'name': name,
            'email': f"{name.lower().replace(' ', '.')}@example.com",
            'password_hash': hash_password("Password@123"),  # Standard password for testing
            'role': role,
            'trust_score': random.randint(40, 100) if role == 'beneficiary' else 100,
            'wallet_address': Web3.to_checksum_address(f"0x{fake.sha256()[:40]}"),
            'aadhar_number': f"{random.randint(1000, 9999)} {random.randint(1000, 9999)} {random.randint(1000, 9999)}",
            'phone': f"9{random.randint(100000000, 999999999)}",
            'created_at': datetime.now(pytz.UTC) - timedelta(days=random.randint(1, 365)),
            'last_login': datetime.now(pytz.UTC) - timedelta(hours=random.randint(1, 72))
        }
        users.append(user)
    
    result = collections['users'].insert_many(users)
    print(f"✅ Generated {len(result.inserted_ids)} realistic users")
    return result.inserted_ids

def generate_dashboard_metrics():
    """Generate and update dashboard metrics collection"""
    metrics = {
        'total_beneficiaries': collections['users'].count_documents({'role': 'beneficiary'}),
        'total_deliveries': collections['deliveries'].count_documents({}),
        'pending_deliveries': collections['deliveries'].count_documents({'status': 'Pending'}),
        'delivered_deliveries': collections['deliveries'].count_documents({'status': 'Delivered'}),
        'disputed_deliveries': collections['deliveries'].count_documents({'status': 'Disputed'}),
        'total_complaints': collections['complaints'].count_documents({}),
        'avg_trust_score': collections['users'].aggregate([
            {'$group': {'_id': None, 'avg': {'$avg': '$trust_score'}}}
        ]).next()['avg'],
        'last_updated': datetime.now(pytz.UTC)
    }
    
    collections['dashboard_metrics'].update_one(
        {}, 
        {'$set': metrics},
        upsert=True
    )
    print("✅ Updated dashboard metrics")
    return metrics

def generate_deliveries_with_timelines(num_deliveries: int):
    """Generate deliveries with realistic timelines for dashboard"""
    beneficiaries = list(collections['users'].find({'role': 'beneficiary'}))
    fps_shops = list(collections['fps'].find())
    
    status_flow = [
        ('Pending', 0.3),
        ('Delivered', 0.6),
        ('Disputed', 0.1)
    ]
    
    deliveries = []
    for _ in range(num_deliveries):
        # Select random beneficiary and FPS
        beneficiary = random.choice(beneficiaries)
        fps = random.choice(fps_shops)
        
        # Determine status based on weighted probability
        status = random.choices(
            [s[0] for s in status_flow],
            weights=[s[1] for s in status_flow]
        )[0]
        
        # Create realistic timeline
        delivery_time = datetime.now(pytz.UTC) - timedelta(days=random.randint(1, 30))
        collection_time = None
        dispute_time = None
        
        if status == 'Delivered':
            collection_time = delivery_time + timedelta(hours=random.randint(1, 72))
        elif status == 'Disputed':
            collection_time = delivery_time + timedelta(hours=random.randint(1, 72))
            dispute_time = collection_time + timedelta(hours=random.randint(1, 24))
        
        delivery = {
            'user_id': beneficiary['_id'],
            'user_name': beneficiary['name'],
            'dealer_id': fps['dealer_id'],
            'dealer_name': fps['dealer_name'],
            'fps_code': fps['fps_code'],
            'items': random.sample([
                {'name': 'Rice', 'quantity': random.randint(5, 10), 'unit': 'kg'},
                {'name': 'Wheat', 'quantity': random.randint(5, 10), 'unit': 'kg'},
                {'name': 'Sugar', 'quantity': random.randint(2, 5), 'unit': 'kg'},
                {'name': 'Kerosene', 'quantity': random.randint(2, 5), 'unit': 'liters'}
            ], random.randint(1, 3)),
            'amount': random.randint(500, 1500),
            'status': status,
            'delivery_time': delivery_time,
            'collection_time': collection_time,
            'dispute_time': dispute_time,
            'timestamp': delivery_time,  # For dashboard sorting
            'blockchain_verified': random.choice([True, False]),
            'fraud_risk': round(random.uniform(0, 0.3 if status != 'Disputed' else 0.7), 2)
        }
        
        deliveries.append(delivery)
    
    result = collections['deliveries'].insert_many(deliveries)
    print(f"✅ Generated {len(result.inserted_ids)} deliveries with timelines")
    
    # Generate corresponding complaints for disputed deliveries
    disputed_deliveries = [d for d in deliveries if d['status'] == 'Disputed']
    generate_complaints_for_deliveries(disputed_deliveries)
    
    return result.inserted_ids

def generate_complaints_for_deliveries(deliveries: list):
    """Generate realistic complaints for disputed deliveries"""
    complaint_types = [
        ("Received less quantity than ordered", "shortage"),
        ("Poor quality items received", "quality"),
        ("Delivery was extremely late", "delay"),
        ("Items were damaged during delivery", "damage"),
        ("Wrong items were delivered", "wrong_items")
    ]
    
    complaints = []
    for delivery in deliveries:
        complaint_text, issue_type = random.choice(complaint_types)
        complaint_text += ". " + fake.sentence()
        
        complaint = {
            'delivery_id': delivery['_id'],
            'user_id': delivery['user_id'],
            'user_name': delivery['user_name'],
            'issue': complaint_text,
            'issue_type': issue_type,
            'status': 'Pending',
            'timestamp': delivery['dispute_time'],
            'severity': round(random.uniform(0.6, 0.9), 2),  # For dashboard
            'priority': random.choice(['high', 'medium', 'low'])
        }
        complaints.append(complaint)
    
    if complaints:
        result = collections['complaints'].insert_many(complaints)
        print(f"✅ Generated {len(result.inserted_ids)} complaints")
    return complaints

def generate_trust_score_history():
    """Generate comprehensive trust score history for dashboard"""
    users = list(collections['users'].find({'role': 'beneficiary'}))
    
    for user in users:
        num_entries = random.randint(3, 10)
        current_score = user['trust_score']
        history = []
        
        for i in range(num_entries):
            change = random.randint(-10, 10)
            new_score = max(0, min(100, current_score + change))
            
            record = {
                'user_id': user['_id'],
                'user_name': user['name'],
                'score': new_score,
                'change': change,
                'reason': random.choice([
                    'Delivery completed',
                    'Complaint resolved',
                    'Late delivery penalty',
                    'Quality issue reported',
                    'Positive feedback reward'
                ]),
                'timestamp': datetime.now(pytz.UTC) - timedelta(days=random.randint(1, 90))
            }
            history.append(record)
            current_score = new_score
        
        collections['trust_scores'].insert_many(history)
    
    print(f"✅ Generated trust score history for {len(users)} beneficiaries")

# --------------------------------------------------
# 🔹 Main Simulation Function
# --------------------------------------------------
def simulate_data():
    print("\n🚀 Starting COMPLETE Data Simulation for AnnSuraksha Dashboard")
    print("="*60)
    
    # Clean old data (careful with this in production)
    for col in collections.values():
        col.drop()
    print("🧹 Cleared existing data collections")
    
    # Generate core data
    print("\n👥 Generating user data...")
    generate_realistic_users(50)
    
    print("\n🏪 Generating FPS shops...")
    generate_fake_fps(15)
    
    print("\n📦 Generating deliveries with timelines...")
    generate_deliveries_with_timelines(200)
    
    print("\n📊 Generating trust score history...")
    generate_trust_score_history()
    
    print("\n📈 Generating dashboard metrics...")
    metrics = generate_dashboard_metrics()
    
    # Final summary
    print("\n" + "="*60)
    print("✅ DATA SIMULATION COMPLETE")
    print("="*60)
    print(f"👥 Total Users: {metrics['total_beneficiaries']} beneficiaries")
    print(f"📦 Total Deliveries: {metrics['total_deliveries']} ({metrics['pending_deliveries']} pending)")
    print(f"⚠️  Total Complaints: {metrics['total_complaints']}")
    print(f"⭐ Average Trust Score: {metrics['avg_trust_score']:.1f}/100")
    print(f"🕒 Last Updated: {metrics['last_updated'].strftime('%Y-%m-%d %H:%M')}")
    print("\nThis data is now ready for your dashboard!")

if __name__ == '__main__':
    simulate_data()