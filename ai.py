import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Optional
import joblib
import requests
import time
import os
from bson.objectid import ObjectId
# Assuming 'db.py' contains the MongoDB collection objects
try:
    from db import (
        deliveries_collection,
        complaints_collection,
        users_collection,
        trust_scores_collection,
        blockchain_logs_collection
    )
except ImportError as e:
    print(f"Error importing database collections: {e}. Ensure 'db.py' is correctly configured.")
    # Consider exiting or providing dummy collections for development
    deliveries_collection = None
    complaints_collection = None
    users_collection = None
    trust_scores_collection = None
    blockchain_logs_collection = None

import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# Constants
TRUST_SCORE_THRESHOLD = 30  # Below this triggers alerts
FRAUD_PROBABILITY_THRESHOLD = 0.85
MODEL_SAVE_PATH = 'ai_models/'

class TrustMonitor:
    def __init__(self):
        self.trust_model = self.load_model('trust_model')
        self.fraud_model = self.load_model('fraud_model')
        self.scaler = self.load_model('scaler')

    def load_model(self, model_name: str):
        """Load pre-trained model or initialize new one"""
        try:
            model = joblib.load(f"{MODEL_SAVE_PATH}{model_name}.joblib")
            # Additional check for scaler
            if model_name == 'scaler' and not hasattr(model, 'mean_'):
                raise ValueError("Scaler not fitted")
            return model
        except (FileNotFoundError, ValueError) as e:
            print(f"No valid {model_name} found, initializing new one: {str(e)}")
            if model_name == 'trust_model':
                return IsolationForest(contamination=0.1, random_state=42)
            elif model_name == 'fraud_model':
                return DBSCAN(eps=0.5, min_samples=5)
            elif model_name == 'scaler':
                return StandardScaler()
            return None

    def save_models(self):
        """Save trained models to disk"""
        if not os.path.exists(MODEL_SAVE_PATH):
            os.makedirs(MODEL_SAVE_PATH)
        joblib.dump(self.trust_model, f"{MODEL_SAVE_PATH}trust_model.joblib")
        joblib.dump(self.fraud_model, f"{MODEL_SAVE_PATH}fraud_model.joblib")
        joblib.dump(self.scaler, f"{MODEL_SAVE_PATH}scaler.joblib")

    def ensure_utc(self, dt: Optional[datetime]) -> datetime:
        """Ensure datetime is timezone-aware in UTC"""
        if dt is None:
            return datetime.now(pytz.UTC)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=pytz.UTC)
        return dt.astimezone(pytz.UTC)

    def get_user_data(self, user_id: str) -> Optional[Dict]:
        """Get comprehensive user data from MongoDB"""
        try:
            if users_collection is None:
                print("Warning: users_collection is not initialized.")
                return None
            user = users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                return None

            deliveries = list(deliveries_collection.find({"user_id": ObjectId(user_id)})) if deliveries_collection else []
            complaints = list(complaints_collection.find({"user_id": ObjectId(user_id)})) if complaints_collection else []
            trust_scores = list(trust_scores_collection.find({"user_id": ObjectId(user_id)})) if trust_scores_collection else []

            return {
                "user": user,
                "deliveries": deliveries,
                "complaints": complaints,
                "trust_scores": trust_scores
            }
        except Exception as e:
            print(f"Error getting user data for {user_id}: {e}")
            return None

    def calculate_behavior_features(self, user_data: Dict) -> Dict:
        """Calculate behavioral features for fraud detection"""
        deliveries = user_data.get("deliveries", [])
        complaints = user_data.get("complaints", [])

        # Basic stats
        total_deliveries = len(deliveries)
        total_complaints = len(complaints)
        avg_delivery_amount = np.mean([d.get("amount", 0) for d in deliveries]) if deliveries else 0

        # Time-based features
        now = datetime.now(pytz.UTC)
        recent_deliveries = []
        for d in deliveries:
            delivery_time = self.ensure_utc(d.get("delivery_time"))
            if (now - delivery_time) < timedelta(days=30):
                recent_deliveries.append(d)

        complaint_ratio = total_complaints / total_deliveries if total_deliveries > 0 else 0

        # Delivery patterns
        delivery_times = []
        for d in deliveries:
            dt = d.get("delivery_time")
            if dt:
                dt = self.ensure_utc(dt)
                delivery_times.append(dt.hour)
        time_std = np.std(delivery_times) if delivery_times else 0

        return {
            "total_deliveries": total_deliveries,
            "total_complaints": total_complaints,
            "complaint_ratio": complaint_ratio,
            "avg_delivery_amount": avg_delivery_amount,
            "recent_deliveries": len(recent_deliveries),
            "delivery_time_std": time_std,
            "trust_score": user_data["user"].get("trust_score", 50) if user_data.get("user") else 50
        }

    def detect_trust_anomalies(self, user_id: str) -> bool:
        """Detect if user's behavior is anomalous based on trust patterns"""
        if not hasattr(self.scaler, 'mean_'):
            print("Scaler not fitted yet - skipping anomaly detection")
            return False

        user_data = self.get_user_data(str(user_id))
        if not user_data:
            return False

        features = self.calculate_behavior_features(user_data)
        feature_vector = np.array(list(features.values())).reshape(1, -1)

        try:
            scaled_features = self.scaler.transform(feature_vector)
            is_anomaly = self.trust_model.predict(scaled_features)
            return is_anomaly[0] == -1
        except Exception as e:
            print(f"Error in anomaly detection: {e}")
            return False

    def detect_fraud_patterns(self, delivery_data: Dict) -> float:
        """Detect potential fraud in delivery patterns"""
        if not hasattr(self.scaler, 'mean_'):
            print("Scaler not fitted yet - skipping fraud detection")
            return 0.0

        if deliveries_collection is None:
            print("Warning: deliveries_collection is not initialized, skipping fraud detection.")
            return 0.0

        user_id = delivery_data.get("user_id")
        if not user_id:
            print("Warning: user_id not found in delivery data, skipping fraud detection.")
            return 0.0

        user_deliveries = list(deliveries_collection.find({
            "user_id": user_id,
            "status": {"$in": ["Delivered", "Pending"]},
        }))

        if not user_deliveries:
            return 0.0

        features = []
        for d in user_deliveries + [delivery_data]:
            dt = self.ensure_utc(d.get("delivery_time"))
            location_str = d.get("location", "0,0")
            try:
                lat, lon = map(float, location_str.split(","))
            except ValueError:
                lat, lon = 0.0, 0.0

            features.append([
                d.get("amount", 0),
                len(d.get("items", [])),
                dt.hour,
                lat,
                lon
            ])

        try:
            scaled_features = self.scaler.transform(features)
            clusters = self.fraud_model.fit_predict(scaled_features)
            return 1.0 if clusters[-1] == -1 else 0.0
        except Exception as e:
            print(f"Error in fraud detection: {e}")
            return 0.0

    def train_models(self):
        """Train models on historical data"""
        print("Training AI models...")

        if users_collection is None or deliveries_collection is None:
            print("Warning: One or more database collections are not initialized. Skipping training.")
            return

        # Get training data
        users = list(users_collection.find({
            "trust_score": {"$exists": True},
            "created_at": {"$lt": datetime.now(pytz.UTC) - timedelta(days=30)}
        }).limit(1000))

        # Create dummy data if no real data exists
        if not users:
            print("No training data available - creating baseline models with dummy data")
            dummy_trust = np.random.rand(50, 7)  # 50 samples, 7 features
            dummy_fraud = np.random.rand(100, 5)  # 100 samples, 5 features

            self.scaler.fit(dummy_trust)
            self.trust_model.fit(self.scaler.transform(dummy_trust))
            self.fraud_model.fit(dummy_fraud)
            self.save_models()
            return

        # Prepare real training data
        X_trust = []
        X_fraud = []

        for user in users:
            user_data = self.get_user_data(str(user["_id"]))
            if not user_data or len(user_data.get("deliveries", [])) < 5:
                continue

            trust_features = self.calculate_behavior_features(user_data)
            X_trust.append(list(trust_features.values()))

            for delivery in user_data.get("deliveries", []):
                dt = self.ensure_utc(delivery.get("delivery_time"))
                location_str = delivery.get("location", "0,0")
                try:
                    lat, lon = map(float, location_str.split(","))
                except ValueError:
                    lat, lon = 0.0, 0.0
                X_fraud.append([
                    delivery.get("amount", 0),
                    len(delivery.get("items", [])),
                    dt.hour,
                    lat,
                    lon
                ])

        # Train models
        if X_trust:
            X_trust = np.array(X_trust)
            self.scaler.fit(X_trust)
            scaled_trust = self.scaler.transform(X_trust)
            self.trust_model.fit(scaled_trust)

        if X_fraud and len(X_fraud) > 10:  # DBSCAN needs minimum samples
            X_fraud = np.array(X_fraud)
            self.fraud_model.fit(X_fraud)

        self.save_models()
        print("Training completed and models saved")

    def real_time_monitor(self):
        """Continuous monitoring for real-time alerts"""
        while True:
            try:
                # Skip if models aren't ready
                if not hasattr(self.scaler, 'mean_'):
                    print("Monitoring paused - models not trained yet")
                    time.sleep(60)
                    continue

                if users_collection is None or deliveries_collection is None:
                    print("Warning: One or more database collections are not initialized. Monitoring paused.")
                    time.sleep(60)
                    continue

                # Check low trust users
                low_trust_users = users_collection.find({
                    "trust_score": {"$lt": TRUST_SCORE_THRESHOLD},
                    "$or": [
                        {"last_alert": {"$lt": datetime.now(pytz.UTC) - timedelta(hours=24)}},
                        {"last_alert": {"$exists": False}}
                    ]
                })

                for user in low_trust_users:
                    if self.detect_trust_anomalies(str(user["_id"])):
                        self.trigger_alert(
                            user_id=str(user["_id"]),
                            alert_type="LOW_TRUST",
                            message=f"User {user.get('name')} has critically low trust score {user.get('trust_score')}"
                        )

                # Check new deliveries
                new_deliveries = deliveries_collection.find({
                    "status": "Pending",
                    "fraud_checked": {"$exists": False}
                })

                for delivery in new_deliveries:
                    fraud_prob = self.detect_fraud_patterns(delivery)
                    if fraud_prob > FRAUD_PROBABILITY_THRESHOLD:
                        self.trigger_alert(
                            delivery_id=str(delivery["_id"]),
                            alert_type="POTENTIAL_FRAUD",
                            message=f"Potential fraud detected in delivery {delivery.get('blockchain_delivery_id')}"
                        )
                    deliveries_collection.update_one(
                        {"_id": delivery["_id"]},
                        {"$set": {"fraud_checked": True, "fraud_probability": fraud_prob}}
                    )

                time.sleep(60 * 5)  # 5 minutes

            except Exception as e:
                print(f"Monitoring error: {str(e)}")
                time.sleep(60)

    def trigger_alert(self, **kwargs):
        """Trigger an alert and log it"""
        alert_data = {
            "timestamp": datetime.now(pytz.UTC),
            "resolved": False,
            **kwargs
        }

        print(f"🚨 ALERT: {alert_data.get('message')}")

        if "user_id" in kwargs and users_collection:
            users_collection.update_one(
                {"_id": ObjectId(kwargs["user_id"])},
                {"$set": {"last_alert": datetime.now(pytz.UTC)}}
            )

        if blockchain_logs_collection:
            blockchain_logs_collection.insert_one({
                "type": "AI_ALERT",
                "data": alert_data,
                "timestamp": datetime.now(pytz.UTC)
            })

    # ... [rest of the class methods unchanged] ...

if __name__ == "__main__":
    # Initialize and verify models
    monitor = TrustMonitor()

    # Check if models need training
    needs_training = (
        not os.path.exists(MODEL_SAVE_PATH) or
        not all(os.path.exists(f"{MODEL_SAVE_PATH}{m}.joblib") for m in ['trust_model', 'fraud_model', 'scaler']) or
        not hasattr(monitor.scaler, 'mean_')
    )

    if needs_training:
        print("Initial model training required...")
        os.makedirs(MODEL_SAVE_PATH, exist_ok=True)
        monitor.train_models()

    # Start monitoring
    import threading
    monitor_thread = threading.Thread(target=monitor.real_time_monitor, daemon=True)
    monitor_thread.start()

    print("AI monitoring system is running in the background...")
    print("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping monitoring system")

def analyze_complaint_text(text: str) -> dict:
    """Analyze complaint text for common issues"""
    issues = {
        "corruption": ["bribe", "scam", "corrupt"],
        "delay": ["late", "delay", "wait"],
        "shortage": ["less", "missing", "shortage"]
    }

    for category, keywords in issues.items():
        if any(kw in text.lower() for kw in keywords):
            return {
                "issue_detected": True,
                "category": category,
                "confidence": 0.9
            }

    return {
        "issue_detected": False,
        "category": "none",
        "confidence": 0.5
    }