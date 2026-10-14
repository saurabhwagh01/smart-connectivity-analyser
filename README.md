# 🌐 Smart Internet Connectivity Analyser

A web-based application for monitoring internet connectivity, measuring network performance, visualizing network history, and analyzing connectivity quality using machine learning.

 <p align="center">
  <a href="https://smart-connectivity-analyser.onrender.com/">
    <img src="https://img.shields.io/badge/Live%20Demo-Visit%20App-2ea44f?style=for-the-badge" alt="Live Demo">
  </a>
  <a href="https://github.com/saurabhwagh01/smart-connectivity-analyser">
    <img src="https://img.shields.io/badge/GitHub-Repository-181717?style=for-the-badge&logo=github" alt="GitHub Repository">
  </a>
</p>
<b>## 📌 Overview</b>

Smart Internet Connectivity Analyser helps users understand their internet connection through network performance measurements, historical statistics, geographical visualization, and AI-powered analysis.

The application combines a responsive web dashboard, a Python backend, a database, and machine learning components to provide insights into connectivity quality.

## 📸 Application Screenshots

> Add your actual application screenshots to the `screenshots/` folder using the filenames shown below. These images will appear here when they are committed to GitHub.

### 🖥️ Main Dashboard

![Smart Connectivity Analyser Dashboard](screenshots/dashboard.png)

### 📊 Network History and Performance

![Network History and Performance Charts](screenshots/network-history.png)

### 🗺️ Connectivity Map

![Connectivity Map](screenshots/connectivity-map.png)

### 🤖 AI Prediction and Anomaly Detection

![AI Prediction and Anomaly Detection](screenshots/ai-analysis.png)

## ✨ Features

- 📡 **Network Performance Monitoring:** Measure download speed, upload speed, ping, jitter, and packet loss where supported by the implementation.
- 📊 **Connectivity Score:** Display a score representing the measured quality of the network connection.
- 🕒 **Network History:** Store and review previous network test results.
- 🗺️ **Interactive Connectivity Map:** Visualize location-related connectivity information using an interactive map.
- 🤖 **AI-Based Prediction:** Use a HistGradientBoosting model for connectivity prediction when the required data is available.
- 🔍 **Anomaly Detection:** Use a Transformer Autoencoder to identify potentially unusual network measurements.
- 📈 **Interactive Dashboard:** Explore network statistics and performance visualizations.
- 🔌 **REST API:** Access backend functionality through FastAPI endpoints.
- 📱 **Responsive Interface:** Access the dashboard through supported desktop and mobile browsers.

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
| ☁️ Deployment | Render |
| 🔧 Version Control | Git, GitHub |

## 🏗️ System Architecture

The application follows a frontend-backend architecture.

1. 🖥️ **Frontend:** Provides the dashboard and handles user interactions.
2. ⚙️ **Backend:** FastAPI processes API requests and application logic.
3. 💾 **Database:** SQLite stores network test history.
4. 🧠 **Machine Learning:** Prediction and anomaly-detection components analyze available network data.
5. 📈 **Visualization:** Charts and maps display connectivity information.
6. ☁️ **Deployment:** Render hosts the web application and backend API.

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
├── screenshots/
│   ├── dashboard.png
│   ├── network-history.png
│   ├── connectivity-map.png
│   └── ai-analysis.png
├── datasets/
├── requirements.txt
├── .gitignore
└── README.md
```

*Note: This is a representative structure. The actual repository may contain additional files and directories.*

## 🚀 Installation and Setup

### 📋 Prerequisites

Install the following tools:

- 🐍 Python version compatible with the project's dependencies
- 🔧 Git
- 💻 Visual Studio Code (recommended)
- 🌐 A modern web browser

### 1️⃣ Clone the Repository

Open a terminal and run:

```bash
git clone https://github.com/saurabhwagh01/smart-connectivity-analyser.git
cd smart-connectivity-analyser
```

### 2️⃣ Create a Virtual Environment

For Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, follow your environment's Python virtual-environment activation instructions.

### 3️⃣ Install Dependencies

Install the packages listed in `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

### 4️⃣ Start the Backend

From the project root, run:

```bash
python -m uvicorn backend.main:app --reload
```

Wait for Uvicorn to report that the server has started successfully.

### 5️⃣ Open the Application

Use these local endpoints:

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
| `GET /api/ai/prediction` | 🔮 Request a connectivity prediction |

Additional endpoints may be available for network testing, history, and other dashboard functionality.

For the complete list of available routes, open the interactive API documentation at `/docs`.

## 🧠 Machine Learning Components

### 🌳 HistGradientBoosting

HistGradientBoosting is a gradient-boosting algorithm used by the application's connectivity prediction component.

Its readiness and prediction quality depend on the availability of suitable data, model artifacts, and successful initialization.

### 🔍 Transformer Autoencoder

The Transformer Autoencoder is used for anomaly detection. It analyzes network measurements to help identify unusual patterns in the available data.

> ⚠️ **Important:** A successful backend health check does not guarantee that all AI models are ready. Model availability and results depend on the deployed configuration and available data.

## ☁️ Deployment

The application is deployed using Render.

🔗 **Live Application:** https://smart-connectivity-analyser.onrender.com/

The configured Uvicorn start command is:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

### Deployment Notes

- 📦 Install the required dependencies from `requirements.txt`.
- ⚙️ Ensure that the Render start command matches the application configuration.
- 💾 Local SQLite data is not automatically transferred from a development machine to Render.
- 🔄 Persistent storage may be required to retain database records across service restarts.
- 🧪 Verify the health endpoint and AI status endpoint after deployment.
- 🔐 Keep credentials and sensitive configuration out of source control.

## 🚧 Future Improvements

- 💾 Add reliable persistent storage for network history.
- 📈 Improve prediction accuracy using more representative training data.
- 🧪 Expand model evaluation using unseen test data and baseline comparisons.
- 🛡️ Improve API error handling and monitoring.
- 📊 Add more network analytics and historical visualizations.
- 📱 Improve mobile usability and accessibility.
- 🔄 Add automated tests and deployment checks.

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome!

1. 🍴 Fork the repository.
2. 🌱 Create a feature branch.
3. 🧪 Implement and test your changes.
4. 📝 Document the changes.
5. 📬 Submit a pull request describing your contribution.

Please make sure that changes are tested and that unrelated files are not included in a pull request.

## 📄 License

No license is specified in this README. Add an appropriate `LICENSE` file before distributing the project or accepting contributions under a defined open-source license.

## 👨‍💻 Author

**Saurabh Wagh**

- 🐙 **GitHub:** https://github.com/saurabhwagh01
- 🌐 **Live Project:** https://smart-connectivity-analyser.onrender.com/

---

⭐ If you find this project interesting, consider starring the repository on GitHub!