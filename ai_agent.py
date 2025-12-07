import os
import subprocess
import sys
import re
from openai import AzureOpenAI

# --- CONFIGURATION ---
# Command to run Angular tests in CI mode (Headless)
TEST_COMMAND = [
    "npm", "run", "test"
]

AZURE_DEPLOYMENT = "gpt-5-chat"

client = AzureOpenAI(
    api_key="1d20e8zxvajgiuGSCyQ2XTU9ZfT7tvMKjRMLrS03JHbhuTpSsE8OJQQJ99BLACHYHv6XJ3w3AAAAACOGLhE2",
    api_version="2025-01-01-preview", # Check your specific Azure version
    azure_endpoint="https://sunee-miu300cs-eastus2.cognitiveservices.azure.com"
)

def strip_ansi(text):
    """Removes color codes from console output."""
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)

def run_tests():
    print("Running Angular unit tests...")
    result = subprocess.run(TEST_COMMAND, capture_output=True, text=True)
    full_output = strip_ansi(result.stdout + result.stderr)
    return result.returncode == 0, full_output

def find_failing_file(log_output):
    """
    Parses Angular/Karma logs to find the culprit file.
    Matches lines like: 'src/app/utils/calc.component.ts'
    """
    # Pattern looks for src/... ending in .ts
    # We prioritize .ts files over .spec.ts because we usually want to fix the logic, not the test.
   
    # 1. Try to find the specific component/service file
    match_ts = re.search(r'(src/[a-zA-Z0-9_\-/]+\.ts)', log_output)
   
    if match_ts:
        file_found = match_ts.group(1)
       
        # If the error points to the spec file, try to infer the component file
        # (Assuming the test is correct and the code is wrong)
        if file_found.endswith('.spec.ts'):
            impl_file = file_found.replace('.spec.ts', '.ts')
            if os.path.exists(impl_file):
                return impl_file
       
        return file_found
       
    return None

def get_fix_from_azure(error_log, file_path, current_code):
    print(f"Requesting fix for {file_path} from Azure OpenAI...")
   
    prompt = f"""
    You are an Expert Angular Developer.
   
    The unit tests are failing.
    File: {file_path}
   
    Code:
    ```typescript
    {current_code}
    ```
   
    Error Stack Trace:
    {error_log}
   
    Task: Fix the code in {file_path} so the tests pass.
    Return ONLY the raw TypeScript code. No markdown, no comments outside code.
    """

    response = client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[
            {"role": "system", "content": "You output only valid TypeScript code."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
   
    # Clean response
    content = response.choices[0].message.content
    content = re.sub(r"^```typescript", "", content, flags=re.MULTILINE)
    content = re.sub(r"^```", "", content, flags=re.MULTILINE)
    content = re.sub(r"```$", "", content, flags=re.MULTILINE)
    return content.strip()

def main():
    # 1. Run tests
    passed, output = run_tests()
   
    if passed:
        print("Tests passed initially. No AI fix needed.")
        sys.exit(0) # Exit success
   
    print("Tests Failed. Identifying failing file...")
   
    # 2. Find file
    failing_file = find_failing_file(output)
    if not failing_file:
        print("Could not parse file path from error log.")
        sys.exit(0) # Exit without erroring the CI (manual review needed)

    print(f"Targeting file: {failing_file}")
   
    # 3. Read Code
    try:
        with open(failing_file, 'r') as f:
            code = f.read()
    except FileNotFoundError:
        print("File not found.")
        sys.exit(0)

    # 4. Get Fix
    fixed_code = get_fix_from_azure(output, failing_file, code)
   
    # 5. Apply Fix
    with open(failing_file, 'w') as f:
        f.write(fixed_code)
       
    # 6. Verify Fix
    print("Verifying fix...")
    passed_retry, output_retry = run_tests()
   
    if passed_retry:
        print("AI Fix Verified! Tests Passed.")
        # Create a marker file for GH Action
        with open("AI_FIX_SUCCESS", "w") as f:
            f.write("true")
    else:
        print("AI Fix Failed. Tests still failing.")
        # Revert changes so we don't commit broken AI code?
        # For now, we leave it, but we won't create the PR.
        sys.exit(1)

if __name__ == "__main__":
    main()
