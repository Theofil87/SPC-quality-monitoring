# SPC Quality Monitoring

Manufacturing-focused **Statistical Process Control (SPC)** project built around a synthetic powder-coating process.

The project demonstrates how production measurements can be transformed into statistical quality insights using **Python, SQL, PostgreSQL, control charts and process capability analysis**.

## 🎯 Objective

The goal is to answer a practical manufacturing question:

> **Is the process stable and capable of meeting specification requirements?**

The project connects shop-floor measurement data with statistical methods used in quality engineering.

## 🔧 What I Built

- Synthetic manufacturing measurement dataset
- PostgreSQL data model and SQL analysis
- SPC-oriented measurement structure
- Control chart calculations and visualization
- Process capability analysis
- **Cp / Cpk** analysis
- **Pp / Ppk** analysis
- Process-centering and variation analysis
- Data preparation for dashboarding and further analytics

## 🏭 Manufacturing Context

The dataset represents a **powder-coating paintshop** with:

- Multiple production booths
- Robotic coating equipment
- Defined measurement points on painted components
- Production and quality measurements
- Multiple shifts and production observations

The synthetic structure is designed to resemble a realistic manufacturing quality-monitoring workflow without exposing confidential production data.

## 📊 Analytics Workflow

```text
Production / Measurement Data
            │
            ▼
        PostgreSQL
            │
            ▼
       SQL Analysis
            │
            ▼
   Python / Statistical Analysis
            │
      ┌─────┴─────┐
      ▼           ▼
 Control Charts  Capability
      │           │
      └─────┬─────┘
            ▼
      Quality Insights
```

## 📐 Statistical Methods

### Control Charts

Control charts are used to distinguish normal process variation from signals that may indicate a process change.

The project focuses on monitoring measurement behaviour over time and identifying potential out-of-control signals.

### Process Capability

The project uses:

- **Cp** — potential process capability based on process variation
- **Cpk** — capability considering process centering
- **Pp** — long-term process performance
- **Ppk** — long-term performance considering centering

This makes it possible to evaluate both process variation and process centering relative to specification limits.

## 🛠️ Technology Stack

- Python
- Pandas
- NumPy
- SciPy
- Matplotlib
- SQL
- PostgreSQL
- Jupyter Notebook
- Git / GitHub

## 📁 Project Structure

```text
SPC-quality-monitoring/
│
├── data/
├── sql/
├── notebooks/
├── src/
├── tests/
├── README.md
└── requirements.txt
```

## 🔍 Why This Project Matters

This project demonstrates the combination of:

**Manufacturing domain knowledge + statistical quality methods + data analytics**

Rather than treating SPC as a purely theoretical topic, the project applies it to a manufacturing scenario and connects the results to practical quality monitoring.

## 🚧 Project Status

🟢 Dataset and manufacturing scenario defined  
🟢 PostgreSQL structure established  
🟢 SQL layer established  
🟢 SPC methodology defined  
🟡 Statistical analysis and dashboard capabilities are being expanded

## 🔮 Next Steps

- Expand control-chart analysis
- Add automated SPC rule detection
- Add interactive Streamlit monitoring
- Add capability reporting by measurement point
- Add trend and shift analysis
- Connect SPC signals with root-cause analysis
- Add automated testing and validation

## 👤 Author

**Béla Páger**

Materials Engineer · Data Analyst · Manufacturing & Quality Analytics

GitHub: https://github.com/Theofil87
