import os
import subprocess
import json
import glob
from openai import AzureOpenAI

# -------------------------------
# Azure OpenAI Client Setup
# -------------------------------
# Required env vars:
#   AZURE_OPENAI_API_KEY
#   AZURE_OPENAI_ENDPOINT (e.g., https://<your-resource>.openai.azure.com)
# Optional:
#   AZURE_OPENAI_API_VERSION (defaults to 2024-10-21)
#   AZURE_OPENAI_DEPLOYMENT (your deployment name, not the model name)
client = AzureOpenAI(
    api_key="FWLxxCnzSHmnO1FXuGmjz3S8TewQNEMJ8c9E9diywAwEnqdh5y4FJQQJ99BLACHYHv6XJ3w3AAAAACOGTVVz", #os.environ.get("AZURE_OPENAI_API_KEY"),
    azure_endpoint="https://sunee-mj00p3qv-eastus2.cognitiveservices.azure.com/", #os.environ.get("AZURE_OPENAI_ENDPOINT"),
    api_version="2023-05-15" #os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
)

# IMPORTANT: This must be the Azure OpenAI *deployment name*, not a raw model ID.
DEPLOYMENT_NAME = "gpt-5-chat" #os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini-deployment")


def get_changes():
    """
    Fetches changed file names and diff content.
    """
    try:
        # Get list of file names
        files = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/main...HEAD"]
        ).decode("utf-8").splitlines()

        # Get diff content (truncated to 15k chars to save cost)
        diff = subprocess.check_output(
            ["git", "diff", "origin/main...HEAD"]
        ).decode("utf-8")
        if len(diff) > 15000:
            diff = diff[:15000] + "\n...[TRUNCATED]"

        return files, diff
    except Exception as e:
        print(f"Error fetching git diff: {e}")
        return [], ""


def get_repo_structure():
    """
    Scans for test files to help the AI map logic to tests.
    """
    patterns = ["**/*.spec.ts"]
    test_files = []
    for pattern in patterns:
        test_files.extend(glob.glob(pattern, recursive=True))
    return test_files


def validate_paths(file_list):
    """Filter out files that don't exist (prevents AI hallucinations)"""
    return [f for f in file_list if os.path.exists(f)]


def ask_ai(changed_files, diff_content, available_tests):
    system_prompt = f"""
You are a Senior DevOps Architect. Analyze code changes to optimize CI resources.

Context:
- Changed Files: {json.dumps(changed_files)}
- Available Tests: {json.dumps(available_tests)}

Task - Return JSON with these keys:
1. "run_snyk": (boolean) TRUE if dependency files (package.json, pom.xml) or security logic (auth, sql) changed.
2. "tests_to_run": (list of strings) specific test paths. If config changes/global impact, return string "ALL".
3. "sonar_inclusions": (list of strings) source paths to scan.
4. "lint_files": (list of strings) source paths to lint.
   - If lint config (.eslintrc, prettierrc, package.json) changed, return string "ALL".
   - Otherwise, return ONLY the changed source code files (js, ts, py, etc).

Output Example:
{{
    "run_snyk": false,
    "tests_to_run": ["src/auth.spec.ts"],
    "sonar_inclusions": ["src/auth.ts"],
    "lint_files": ["src/auth.ts"]
}}
"""

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,  # Azure deployment name
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Git Diff:\n{diff_content}"},
            ],
            # Structured output for safer JSON parsing (supported in the latest Azure OpenAI API versions)
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content

        # Defensive parse + normalize keys
        decisions = json.loads(content)
        # Fill any missing keys with safe defaults
        decisions.setdefault("run_snyk", False)
        decisions.setdefault("tests_to_run", [])
        decisions.setdefault("sonar_inclusions", [])
        decisions.setdefault("lint_files", [])

        return decisions

    except Exception as e:
        # Bubble up for top-level fail-safe handling
        raise RuntimeError(f"Azure OpenAI call failed: {e}")


def write_github_output(decisions):
    output_file = os.environ.get("GITHUB_OUTPUT", "output.txt")

    with open(output_file, "a") as fh:
        # --- SNYK ---
        print(f"Snyk: {decisions['run_snyk']}")
        fh.write(f"run_snyk={str(decisions['run_snyk']).lower()}\n")

        # --- LINT ---
        lint_target = decisions.get("lint_files", [])
        if lint_target == "ALL":
            print("Lint: ALL")
            fh.write("lint_command=npm run lint\n")  # Adjust to your command
        else:
            valid_lint = validate_paths(lint_target)
            if valid_lint:
                print(f"Linting specific files: {len(valid_lint)}")
                # Using npx eslint directly allows passing file arguments
                fh.write(f"lint_command=npx eslint {' '.join(valid_lint)}\n")
            else:
                fh.write("lint_command=echo 'No files to lint'\n")

        # --- TESTS ---
        tests = decisions.get("tests_to_run", [])
        if tests == "ALL":
            print("Tests: ALL")
            fh.write("test_command=npm test\n")
        else:
            valid_tests = validate_paths(tests)
            if valid_tests:
                print(f"Tests Selected: {len(valid_tests)}")
                fh.write(f"test_command=npm test -- {' '.join(valid_tests)}\n")
            else:
                fh.write("test_command=echo 'No tests required'\n")

        # --- SONAR ---
        sonar_files = validate_paths(decisions.get("sonar_inclusions", []))
        if sonar_files:
            print(f"Sonar: Scanning {len(sonar_files)} files")
            fh.write("run_sonar=true\n")
            fh.write(f"sonar_inclusions={','.join(sonar_files)}\n")
        else:
            fh.write("run_sonar=false\n")


if __name__ == "__main__":
    files, diff = get_changes()
    if not files:
        print("No changes.")
        exit(0)

    try:
        decisions = ask_ai(files, diff, get_repo_structure())
        write_github_output(decisions)
    except Exception as e:
        print(f"AI Error: {e}")
        # FAILSAFE: Run everything
        with open(os.environ.get("GITHUB_OUTPUT", "output.txt"), "a") as fh:
            fh.write("run_snyk=true\nrun_sonar=true\nsonar_inclusions=**/*\n")
            fh.write("test_command=npm test\nlint_command=npm run lint\n")
