# 🌐 Smart Internet Connectivity Analyser

A web-based application for monitoring internet connectivity, measuring network performance, visualizing connectivity history, and analyzing network quality using machine learning.

🔗 **Live Demo:** https://smart-connectivity-analyser.onrender.com/

💻 **GitHub Repository:** https://github.com/saurabhwagh01/smart-connectivity-analyser

## 📌 Overview

Smart Internet Connectivity Analyser helps users understand their internet connection through network performance measurements, historical statistics, geographical visualization, and AI-powered analysis.

The application combines a responsive web dashboard with a Python backend and machine learning components to provide insights into connectivity quality.

## ✨ Features

- 📡 **Network Performance Monitoring:** Measure download speed, upload speed, ping, jitter, and packet loss where supported by the measurement implementation.
- 📊 **Connectivity Score:** Display a score representing the measured quality of the network connection.
- 🕒 **Network History:** Store and review previous network test results.
- 🗺️ **Interactive Connectivity Map:** Visualize location-related connectivity information using a map interface.
- 🤖 **AI-Based Prediction:** Use a HistGradientBoosting model to estimate connectivity performance when the required data is available.
- 🔍 **Anomaly Detection:** Use a Transformer Autoencoder to identify potentially unusual network measurements.
- 📈 **Interactive Dashboard:** View network statistics and visualizations through a responsive interface.
- 🔌 **REST API:** Access backend functionality through FastAPI endpoints.

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| 🎨 Frontend | HTML, CSS, JavaScript |
| ⚙️ Backend | Python, FastAPI |
| 🚀 ASGI Server | Uvicorn |
| 🧠 Machine Learning | scikit-learn |
| 🔬 Deep Learning | PyTorch |
| 💾 Database | SQLite |
| 📊 Charts | Chart.js |
| 🌍 Maps | Leaflet, OpenStreetMap |

## 🏗️ System Architecture

The application follows a frontend-backend architecture.

1. 🖥️ The frontend provides the dashboard and handles user interactions.
2. ⚙️ The FastAPI backend handles API requests and network-test data.
3. 💾 SQLite stores network history.
4. 🧠 Machine learning components perform prediction and anomaly analysis.
5. 📈 Charting and mapping libraries visualize the available results.

## 📂 Project Structure

```text
smart-connectivity-analyser/
├── backend/
│   ├── main.py
│   ├── ai_engine.py
│   ├── final_predictor.py
│   └── models/
├── css/
├── js/
├── datasets/
├── requirements.txt
├── .gitignore
└── README.md
```

*Note: This is a representative structure. Your repository may contain additional files and directories.*

## 🚀 Installation and Setup

### 📋 Prerequisites

Install the following:

- 🐍 Python 3.11 or another version supported by the project's dependencies
- 🔧 Git
- 💻 Visual Studio Code (recommended)

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/saurabhwagh01/smart-connectivity-analyser.git
cd smart-connectivity-analyser
```

### 2️⃣ Create a Virtual Environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the environment's Python executable directly instead.

### 3️⃣ Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 4️⃣ Start the Backend

Run this command from the project root:

```bash
python -m uvicorn backend.main:app --reload
```

### 5️⃣ Open the Application

- 🌐 **Backend API:** http://127.0.0.1:8000
- 📚 **Interactive API Documentation:** http://127.0.0.1:8000/docs
- ❤️ **Health Check:** http://127.0.0.1:8000/api/health

If the frontend is served by FastAPI, open the local application URL in your browser. Otherwise, follow the frontend-specific instructions in the repository.

## 🔌 API Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | 🏠 Application entry point |
| `GET /api/health` | ❤️ Check backend health |
| `GET /api/ai/status` | 🧠 Inspect AI model readiness |
| `GET /api/ai/prediction` | 🔮 Request connectivity prediction |

Additional endpoints may be available for network testing, history, and other dashboard features. Visit `/docs` to inspect the actual API routes.

## 🧠 Machine Learning Components

### 🌳 HistGradientBoosting

A gradient-boosting model used for connectivity prediction. Prediction readiness depends on the availability of suitable input data and successful model initialization.

### 🔍 Transformer Autoencoder

A deep-learning model used for anomaly detection. It analyzes network measurements to help identify unusual patterns.

> ⚠️ **Note:** Model availability and prediction quality depend on the deployed configuration, data availability, and model artifacts. A successful backend health check does not guarantee that every AI model is ready.

## ☁️ Deployment

The application is deployed on Render.

🔗 **Live Application:** https://smart-connectivity-analyser.onrender.com/

The deployment uses Uvicorn to serve the FastAPI application. The configured start command is:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

The database and any required model files must be available in the deployed environment. Local SQLite data is not automatically transferred to Render, and persistent storage may be required to retain history across service restarts.

## 🚧 Future Improvements

- 💾 Persistent database storage for reliable historical records
- 📈 Improved prediction accuracy through additional representative data
- 🧪 Model evaluation using unseen test data and appropriate baseline comparisons
- 🛡️ Better monitoring of API and model failures
- 📊 Expanded connectivity analytics and historical visualizations
- 🔄 Automated deployment checks and testing

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome!

1. 🍴 Fork the repository.
2. 🌱 Create a feature branch.
3. 🧪 Make and test your changes.
4. 📬 Submit a pull request describing the changes.

## 📄 License

Add the appropriate license for this project before distributing or accepting contributions. No license is specified in this README.

## 👨‍💻 Author

**Saurabh Wagh**

🐙 GitHub: https://github.com/saurabhwagh01
