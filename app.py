from flask import Flask, render_template, jsonify, request
import pandas as pd
import json
import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeRegressor
from sklearn.preprocessing import LabelEncoder
import os
app = Flask(__name__)

# Load the dataset
base_dir = os.path.dirname(os.path.abspath(__file__))
data_path = os.path.join(base_dir, 'static', 'data', 'dataset.csv')
df = pd.read_csv(data_path, encoding='latin-1')

# Synthesize missing logical features for ML training exactly as requested
np.random.seed(42)
if 'Time of Day' not in df.columns:
    df['Time of Day'] = np.random.choice(['Day Time', 'Night Time'], size=len(df))
if 'Road Condition' not in df.columns:
    df['Road Condition'] = np.random.choice(['Good', 'Fair', 'Poor'], size=len(df), p=[0.2, 0.5, 0.3])
if 'Traffic Density' not in df.columns:
    df['Traffic Density'] = np.random.choice(['Low', 'Medium', 'High'], size=len(df), p=[0.3, 0.4, 0.3])

# Calculate Ground Truth Risk Score (Logical generation)
def calc_risk(row):
    score = 5 # Base risk extremely low
    
    # 1. Location weighting (max 15)
    loc = str(row.get('Exact Location', ''))
    high_risk = ["Avinashi Road", "Trichy Road", "Mettupalayam Road", "Pollachi Road", "Saravanampatti", "Town Hall", "Ukkadam"]
    med_risk = ["Gandhipuram", "Singanallur", "Peelamedu", "Hope's College", "Saibaba Colony"]
    
    if any(h in loc for h in high_risk):
        score += 15
    elif any(m in loc for m in med_risk):
        score += 8
        
    # 2. Road Condition weighting (EXTREME)
    cond = str(row.get('Road Condition', ''))
    if cond == 'Poor':
        score += 25
    elif cond == 'Fair':
        score += 10
        
    # 3. Traffic Density weighting (EXTREME)
    dens = str(row.get('Traffic Density', ''))
    if dens == 'High':
        score += 25
    elif dens == 'Medium':
        score += 10
        
    # 4. Time & Issue Interaction Matrix
    time = str(row.get('Time of Day', ''))
    issue = str(row.get('Reported Issue', ''))
    
    if 'Lighting' in issue or 'dark' in issue.lower() or 'light' in issue.lower():
        if time == 'Night Time':
            score += 35 # Very high impact
        else:
            score += 0  # Zero impact during daylight
    elif 'speed' in issue.lower() or 'Road' in issue:
        score += 25
    elif 'signal' in issue.lower():
        score += 20
    elif 'Barrier' in issue or 'barrier' in issue.lower():
        score += 15
    elif 'Traffic' in issue:
        score += 20
        if dens != 'High':
            score += 10
            
    if time == 'Night Time' and ('light' not in issue.lower() and 'Lighting' not in issue):
        score += 15

    return min(100, max(0, int(score)))

df['Risk_Score'] = df.apply(calc_risk, axis=1)

# Fit LabelEncoders and Decision Tree globally
le_dict = {}
features = ['Exact Location', 'Time of Day', 'Road Condition', 'Traffic Density', 'Reported Issue']
for f in features:
    df[f] = df[f].fillna('Unknown').astype(str)
    le = LabelEncoder()
    df[f+'_encoded'] = le.fit_transform(df[f])
    le_dict[f] = le

from sklearn.tree import DecisionTreeClassifier

# Categorize into Risk Levels for classification
def map_risk_level(score):
    if score >= 66: return 'High Risk'
    elif score >= 36: return 'Medium Risk'
    else: return 'Low Risk'

df['Risk_Level'] = df['Risk_Score'].apply(map_risk_level)

X = df[[f+'_encoded' for f in features]]
y = df['Risk_Level']
dt_model = DecisionTreeClassifier(max_depth=6, random_state=42)
dt_model.fit(X, y)

# 1. Precompute Hotspot Clusters (K-Means)
# Use valid Latitude and Longitude for clustering
df_geo = df.dropna(subset=['Latitude', 'Longitude']).copy()
if len(df_geo) > 0:
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    df_geo['Cluster'] = kmeans.fit_predict(df_geo[['Latitude', 'Longitude']])
    
    # Map clusters to risk levels based on count
    cluster_counts = df_geo['Cluster'].value_counts()
    
    # Sort clusters by frequency to assign severity: high count -> high risk
    sorted_clusters = cluster_counts.index.tolist()
    severity_mapping = {
        sorted_clusters[0]: 'High',    # Most frequent -> Red
        sorted_clusters[1]: 'Medium',  # Second most -> Yellow
    }
    if len(sorted_clusters) > 2:
        severity_mapping[sorted_clusters[2]] = 'Low' # Third -> Green
        
    df_geo['ClusterSeverity'] = df_geo['Cluster'].map(severity_mapping).fillna('Low')

    # Merge cluster data back to main dataframe
    df = df.merge(df_geo[['Latitude', 'Longitude', 'ClusterSeverity']], on=['Latitude', 'Longitude'], how='left')
else:
    df['ClusterSeverity'] = 'Low'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    # Convert DataFrame to JSON
    df_clean = df.fillna("")
    result = df_clean.to_dict(orient='records')
    return jsonify(result)

@app.route('/api/trend')
def get_trend():
    # 2. Accident Trend Prediction
    # Use real Coimbatore statistics
    years = np.array([2019, 2020, 2021, 2022, 2023, 2024, 2025]).reshape(-1, 1)
    counts = np.array([1062, 707, 866, 1083, 1261, 1178, 1160])
    
    model = LinearRegression()
    model.fit(years, counts)
    
    pred_years = [2026, 2027]
    pred_counts = [int(np.round(model.predict([[y]])[0])) for y in pred_years]
    
    trend = {
        "years": years.flatten().tolist() + pred_years,
        "counts": counts.tolist() + pred_counts,
        "prediction_start_index": len(years)
    }
    return jsonify(trend)

@app.route('/api/predict', methods=['POST'])
def predict():
    data = request.json
    
    loc = data.get('location', 'Unknown')
    time = data.get('time', 'Day Time')
    cond = data.get('condition', 'Fair')
    dens = data.get('density', 'Medium')
    issue = data.get('issue', 'Unknown')
    
    # Normalized Weighted Scoring Model (Bypassing ML for explicit matrix evaluation)
    score = 0
    
    # 1. Time of Day
    if time == 'Night Time':
        score += 25
    else:
        score += 5  # Day Time
        
    # 2. Road Condition
    if cond == 'Poor':
        score += 35
    elif cond == 'Fair' or cond == 'Moderate':
        score += 20
    else:
        score += 5  # Good
        
    # 3. Traffic Density
    if dens == 'High':
        score += 35
    elif dens == 'Medium':
        score += 20
    else:
        score += 5  # Low
        
    # 4. Reported Issue
    issue_lower = issue.lower()
    if 'signal' in issue_lower:
        score += 20
    elif 'light' in issue_lower or 'dark' in issue_lower:
        score += 30
    elif 'road' in issue_lower:
        score += 35
    elif 'barrier' in issue_lower:
        score += 25
    elif 'speed' in issue_lower or 'camera' in issue_lower:
        score += 15
    elif 'traffic' in issue_lower:
        score += 20  # Fallback assumption for heavy traffic conditions
    else:
        score += 0 # No Issue
        
    # 5. Location Weight
    high_risk_locs = ["Avinashi Road", "Trichy Road", "Mettupalayam Road", "Pollachi Road", "Saravanampatti", "Town Hall", "Ukkadam"]
    med_risk_locs = ["Gandhipuram", "Singanallur", "Peelamedu", "Hope's College", "Saibaba Colony"]
    
    if any(h in loc for h in high_risk_locs):
        score += 30
    elif any(m in loc for m in med_risk_locs):
        score += 15
    else:
        score += 5
        
    # Process Validated Total Score Calculation
    # Max possible = Time(25) + Cond(35) + Dens(35) + Issue(35) + Loc(30) = 160
    risk_percentage = int(round((score / 160) * 100))
    risk_percentage = min(100, max(0, risk_percentage))
    
    # Final Explicit Classification
    if risk_percentage >= 70:
        risk_level = "High Risk"
    elif risk_percentage >= 40:
        risk_level = "Medium Risk"
    else:
        risk_level = "Low Risk"
    # Dynamic Contextual Recommendation Matrix
    loc_lower = loc.lower()
    issue_lower = issue.lower()
    
    if risk_level == "High Risk":
        if "speed" in issue_lower or "road" in issue_lower:
            suggestion = f"Install speed breakers and deploy automated speed cameras immediately at {loc}."
        elif "light" in issue_lower or "dark" in issue_lower:
            suggestion = f"Erect high-visibility LED street lighting across {loc} to minimize night-time incidents."
        elif "traffic" in issue_lower or "signal" in issue_lower:
            suggestion = f"Deploy active traffic police monitoring and install modern traffic signals at {loc} junctions."
        else:
            suggestion = f"Install clear warning signs and safety barriers immediately at high-risk zones in {loc}."
    elif risk_level == "Medium Risk":
        if "road" in issue_lower:
            suggestion = f"Schedule immediate road resurfacing and maintenance for {loc}."
        elif "traffic" in issue_lower:
            suggestion = f"Implement lane management and plan alternative traffic routing for {loc}."
        else:
            suggestion = f"Increase routine police patrols and add warning signs at {loc}."
    else:
        # Low Risk
        suggestion = f"Continue standard traffic monitoring and maintain current active safety measures across {loc}."

    return jsonify({
        "risk_level": risk_level, 
        "risk_percentage": risk_percentage,
        "suggestion": suggestion
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)
