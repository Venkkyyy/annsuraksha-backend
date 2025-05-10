# app.py
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient
from datetime import datetime, timedelta
from pytz import timezone
from ai import analyze_complaint_text
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static frontend
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")  # Default to localhost if not in .env
client = MongoClient(MONGO_URI)
db = client["AnnSuraksha"]
users_collection = db["users"]
deliveries_collection = db["deliveries"]
complaints_collection = db["complaints"]
blockchain_logs_collection = db["blockchain_logs"]

# Serve pages.  Make sure these paths match your file structure.
@app.get("/")
async def serve_register() -> FileResponse: # Added return type
    return FileResponse("frontend/register.html")

@app.get("/login-page")
async def serve_login_page() -> FileResponse: # Added return type
    return FileResponse("frontend/login.html")

@app.get("/dashboard")
async def serve_dashboard() -> FileResponse: # Added return type
    return FileResponse("frontend/dashboard.html")

@app.get("/health")
async def health_check() -> dict: # Added return type
    return {"status": "ok"}

# Register
@app.post("/register")
async def register_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
) -> dict: # Added return type
    if users_collection.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_data = {
        "name": name,
        "email": email,
        "password": password,
        "role": role,
        "trust_score": 100,
        "created_at": datetime.now(timezone("Asia/Kolkata")) # Added created_at
    }
    users_collection.insert_one(user_data)
    return {"message": "User registered successfully"}

# Login
@app.post("/api/login")
async def login_user(request: Request) -> dict: # Added return type
    data = await request.json()
    user = users_collection.find_one({"email": data.get("email")})
    if not user or user["password"] != data.get("password"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"token": "dummy-token", "message": "Login successful"}

# Log delivery
@app.post("/delivery")
async def log_delivery(delivery: dict) -> dict: # Added return type
    user = users_collection.find_one({"aadhar_number": delivery["aadhar_number"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    delivery["created_at"] = datetime.now(timezone("Asia/Kolkata"))
    deliveries_collection.insert_one(delivery)
    trust_score = compute_trust_score(delivery)
    users_collection.update_one({"aadhar_number": delivery["aadhar_number"]}, {"$set": {"trust_score": trust_score}})
    blockchain_logs_collection.insert_one({
        "aadhar_number": delivery["aadhar_number"],
        "action": "Delivery Logged",
        "trust_score": trust_score,
        "timestamp": datetime.now(timezone("Asia/Kolkata"))
    })
    return {"message": "Delivery logged"}

# Log complaint
@app.post("/complaint")
async def log_complaint(complaint: dict) -> dict: # Added return type
    user = users_collection.find_one({"aadhar_number": complaint["aadhar_number"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    complaint["created_at"] = datetime.now(timezone("Asia/Kolkata"))
    complaints_collection.insert_one(complaint)
    ai_result = analyze_complaint_text(complaint["text"])
    blockchain_logs_collection.insert_one({
        "aadhar_number": complaint["aadhar_number"],
        "action": "Complaint Filed",
        "severity": ai_result["severity"],
        "timestamp": datetime.now(timezone("Asia/Kolkata"))
    })
    return {"message": "Complaint filed", "ai_result": ai_result}

# Complaint listing
@app.get("/complaints")
async def get_all_complaints() -> List[dict]: # Added return type
    complaints = list(complaints_collection.find().sort("created_at", -1))
    for c in complaints:
        c["_id"] = str(c["_id"])
        c["created_at"] = c["created_at"].isoformat()
    return complaints

# Trust score overview
@app.get("/trust_scores/overview")
async def get_trust_score_overview() -> dict: # Added return type
    scores = list(users_collection.find({}, {"trust_score": 1}))
    trust_values = [u["trust_score"] for u in scores if isinstance(u.get("trust_score"), (int, float))]
    if not trust_values:
        return {"average": 0, "min": 0, "max": 0, "count": 0}
    return {
        "average": round(sum(trust_values) / len(trust_values), 2),
        "min": min(trust_values),
        "max": max(trust_values),
        "count": len(trust_values)
    }

# Trust by aadhar
@app.get("/trust_scores/{aadhar_number}")
async def get_trust_score(aadhar_number: str) -> dict: # Added return type
    user = users_collection.find_one({"aadhar_number": aadhar_number})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"trust_score": user.get("trust_score", 100)}

@app.get("/dashboard/recent_deliveries")
async def get_recent_deliveries(limit: int = 5):
    recent = list(deliveries_collection.find().sort("created_at", -1).limit(limit))
    for d in recent:
        d["_id"] = str(d.get("_id", ""))
        d["created_at"] = d.get("created_at", datetime.now()).isoformat()
        d["details"] = d.get("details", "Delivery logged")
        d["user_id"] = d.get("user_id", "N/A")
    return recent



@app.get("/dashboard/metrics")
async def get_dashboard_metrics() -> dict: # Added return type
    return {
        "total_deliveries": deliveries_collection.count_documents({}),
        "total_complaints": complaints_collection.count_documents({})
    }

@app.get("/dashboard/active_complaints")
async def get_active_complaints():
    data = list(complaints_collection.find().sort("created_at", -1).limit(5))
    result = []
    for c in data:
        result.append({
            "user_name": c.get("user_name", "Unknown"),
            "issue": c.get("text", "N/A"),
            "severity": c.get("severity", "-"),
            "priority": c.get("priority", "-"),
            "status": c.get("status", "Pending"),
            "created_at": c.get("created_at", datetime.now()).isoformat()
        })
    return result


@app.get("/alerts/recent")
async def get_recent_alerts(limit: int = 5) -> List[dict]:
    alerts = list(blockchain_logs_collection.find({"action": "Complaint Filed"}).sort("timestamp", -1).limit(limit))
    for alert in alerts:
        alert["_id"] = str(alert["_id"])
        alert["timestamp"] = alert["timestamp"].isoformat()
    return alerts
@app.get("/timeline")
async def get_timeline_events(limit: int = 10):
    timeline = []

    deliveries = list(deliveries_collection.find().sort("created_at", -1).limit(limit))
    for d in deliveries:
        timeline.append({
            "type": "delivery",
            "aadhar_number": d.get("user_id", "Unknown"),
            "timestamp": d.get("created_at", datetime.now()).isoformat(),
            "details": d.get("details", "Delivery logged")
        })

    complaints = list(complaints_collection.find().sort("created_at", -1).limit(limit))
    for c in complaints:
        timeline.append({
            "type": "complaint",
            "aadhar_number": c.get("user_id", "Unknown"),
            "timestamp": c.get("created_at", datetime.now()).isoformat(),
            "details": c.get("text", "Complaint filed")
        })

    timeline.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline[:limit]


# Helper function
def compute_trust_score(delivery: dict) -> int:
    """Computes trust score based on delivery status.  Penalizes delayed deliveries."""
    base_score = 100
    penalty = 0

    # Check for delays.
    if delivery.get("collection_time") and delivery.get("delivery_time"):
        if delivery["collection_time"] > delivery["delivery_time"] + timedelta(hours=24):
            penalty += 10

    final_score = max(0, base_score - penalty)
    return final_score
dao_votes_collection = db["dao_votes"]

@app.post("/dao/vote")
async def dao_vote(request: Request):
    data = await request.json()
    dealer_id = data.get("dealer_id")
    vote = data.get("vote")  # "yes" or "no"
    voter = data.get("voter_email")

    if not all([dealer_id, vote, voter]):
        raise HTTPException(status_code=400, detail="Missing vote data")

    dao_votes_collection.insert_one({
        "dealer_id": dealer_id,
        "vote": vote,
        "voter_email": voter,
        "timestamp": datetime.now(timezone("Asia/Kolkata"))
    })

    return {"message": "Vote recorded"}

@app.get("/dao/results/{dealer_id}")
async def dao_results(dealer_id: str):
    yes_votes = dao_votes_collection.count_documents({"dealer_id": dealer_id, "vote": "yes"})
    no_votes = dao_votes_collection.count_documents({"dealer_id": dealer_id, "vote": "no"})
    return {"yes": yes_votes, "no": no_votes}
