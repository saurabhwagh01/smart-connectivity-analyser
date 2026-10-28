# Contributing to Smart Internet Connectivity Analyser

Thank you for your interest in contributing to Smart Internet Connectivity Analyser! Contributions from beginners and experienced developers are welcome.

Please read these guidelines before making changes to the project.

## 1. About the Project

Smart Internet Connectivity Analyser is a web application that monitors internet connectivity, analyses network performance, visualises historical data, and explores AI-powered connectivity predictions and anomaly detection.

The project uses HTML, CSS, JavaScript, Python, FastAPI, SQLite, and machine-learning tools.

## 2. Where to Start

If you are new to the project, follow these steps:

1. Read the project's [README.md](README.md).
2. Explore the project structure and understand the relevant files.
3. Visit the [GitHub Issues](https://github.com/saurabhwagh01/smart-connectivity-analyser/issues) page.
4. Look for an issue that matches your interests and skill level.
5. Read the issue description and acceptance criteria carefully.
6. Ask questions in the issue comments if anything is unclear.
7. Wait for confirmation before beginning work on an issue that requires assignment or approval.

Beginners can start with documentation improvements, small bug fixes, or clearly defined frontend tasks.

## 3. Setting Up the Project Locally

### Prerequisites

Install the following tools:

- Python and pip
- Git
- A modern web browser
- Visual Studio Code or another code editor

Check the README for the recommended Python version and setup instructions.

### Installation

Clone the repository:

```bash
git clone https://github.com/saurabhwagh01/smart-connectivity-analyser.git
cd smart-connectivity-analyser
```

Create and activate a virtual environment.

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS or Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the backend:

```bash
python -m uvicorn backend.main:app --reload
```

The backend should be available at:

`http://127.0.0.1:8000/`

For API documentation, visit:

`http://127.0.0.1:8000/docs`

Follow the README instructions to open the frontend and configure its API connection for local development.

## 4. Finding and Claiming Issues

- Review existing issues before creating a new one.
- Check whether the issue is already assigned to another contributor.
- Comment on an issue to express your interest and explain how you plan to approach it.
- Wait for confirmation from the project maintainers when assignment is required.
- Ask for clarification before making assumptions about expected behaviour.
- Work on one issue at a time unless the maintainers approve otherwise.
- Do not begin substantial work on an issue assigned to someone else.

If you discover a bug, provide clear reproduction steps and describe the expected and actual behaviour.

## 5. Development Guidelines

- Keep changes focused on the issue being addressed.
- Follow the existing code style and project structure.
- Use clear, descriptive names for variables, functions, and files.
- Avoid introducing unnecessary dependencies.
- Do not commit API keys, passwords, tokens, private information, or local environment files.
- Do not commit generated data or database changes unless they are required for the task.
- Update documentation when changes affect setup, features, or behaviour.
- Explain important assumptions in your pull request.
- Avoid unrelated changes that make code reviews more difficult.

## 6. Testing Your Changes

Before submitting a pull request:

1. Run the application locally when possible.
2. Test the functionality affected by your changes.
3. Check for errors in the browser console and backend terminal.
4. Verify that existing features still work.
5. Include relevant test results or explain any tests you could not run.

Do not claim that a test passed unless you actually ran it.

### Testing Machine-Learning Features

For changes involving machine-learning functionality:

- Use a documented dataset or a clearly identified test dataset.
- Keep training and evaluation data separate when evaluating model performance.
- Use appropriate baseline models when comparing prediction performance.
- Report the evaluation metrics actually produced by your experiments.
- Do not claim improved accuracy without comparing results against a suitable baseline.
- Document important preprocessing steps and assumptions.
- Do not fabricate missing measurements or evaluation results.

## 7. Pull Request Process

1. Fork the repository if you do not have write access.
2. Create a separate branch for your work.

   ```bash
   git checkout -b fix/short-description
   ```

3. Make your changes and test them.
4. Stage only the files relevant to your changes.

   ```bash
   git add <specific-file>
   ```

5. Commit your changes with a descriptive message.

   ```bash
   git commit -m "docs: improve contributor instructions"
   ```

6. Push your branch to your fork.

   ```bash
   git push origin fix/short-description
   ```

7. Open a pull request against the appropriate branch of the original repository.
8. Describe the problem, your solution, and the tests you performed.
9. Link the related issue when applicable.
10. Respond respectfully to review feedback and make requested changes.

If you have direct repository write access, follow the maintainers' instructions about branching and pull requests.

Before pushing, check that you are on the correct branch and that you have not staged secrets, local configuration, generated datasets, or unrelated files.

## 8. Commit Message Guidelines

Use short, descriptive commit messages.

Examples:

- `docs: improve contributor instructions`
- `fix: handle missing network measurements`
- `feat: improve network history display`
- `test: add API endpoint tests`
- `refactor: simplify connectivity analysis`

Use a prefix that describes the type of change when appropriate.

## 9. AI-Assisted Contributions

If you use AI tools while contributing:

- Follow the project's AI-use policy and any event-specific rules.
- Understand the code or documentation you submit.
- Review generated suggestions for correctness, security, and compatibility.
- Test AI-assisted code before submitting it.
- Disclose AI assistance when required by the applicable policy.
- Never submit code you cannot explain or verify.

If the project maintainers publish a more specific AI-use policy, follow that policy.

## 10. Code of Conduct

Be respectful, welcoming, and constructive when communicating with maintainers and other contributors.

- Treat everyone with respect.
- Welcome questions from beginners.
- Give feedback that helps others improve.
- Avoid harassment, discrimination, personal attacks, and disrespectful behaviour.
- Discuss technical disagreements professionally.

Contributors are expected to maintain a collaborative and inclusive environment.

## 11. Questions and Support

For project-specific questions, open or comment on a relevant GitHub issue.

For bugs or feature requests:

1. Check existing issues before creating a new one.
2. Provide clear steps to reproduce the problem.
3. Include relevant error messages or screenshots when appropriate.
4. Explain the expected behaviour and what happened instead.

Avoid sharing passwords, API keys, private information, or other sensitive data in public issues.

Thank you for helping improve Smart Internet Connectivity Analyser!