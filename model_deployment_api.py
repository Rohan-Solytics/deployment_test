import os
import sys
import subprocess
import glob
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
import psutil
import yaml

app = FastAPI()

class ModelDeployment(BaseModel):
    deployment_name: str = Field(..., description="Name for this model deployment")
    requirements_file: str = Field(..., description="Name of the requirements file to use")

deployed_models = {}
global next_port
next_port = 5000

# Load configuration
with open('config.yaml', 'r') as config_file:
    config = yaml.safe_load(config_file)

CPU_LIMIT = config['cpu_limit']
RAM_LIMIT = config['ram_limit']

def check_resource_availability():
    cpu_percent = psutil.cpu_percent()
    ram_percent = psutil.virtual_memory().percent
    return cpu_percent < CPU_LIMIT and ram_percent < RAM_LIMIT

def create_venv(venv_name):
    subprocess.run([sys.executable, '-m', 'venv', venv_name], check=True)

def install_requirements(venv_name, req_file):
    if os.name == 'nt':  # Windows
        pip_path = os.path.join(venv_name, 'Scripts', 'pip')
    else:  # Unix-based systems
        pip_path = os.path.join(venv_name, 'bin', 'pip')
    
    print(f"Using pip: {pip_path}")
    print(f"Installing from: {req_file}")
    
    try:
        result = subprocess.run([pip_path, 'install', '-r', req_file], capture_output=True, text=True, check=True)
        print(f"Installation output:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error installing requirements for {req_file}:")
        print(f"Exit code: {e.returncode}")
        print(f"Error output:\n{e.stderr}")
        raise HTTPException(status_code=500, detail=f"Failed to install requirements: {e.stderr}")

def create_model_script(deployment_name, port):
    script_content = f"""
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get('/')
def read_root():
    return {{'message': 'Model {deployment_name} is running'}}

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port={port})
"""
    script_path = f"{deployment_name}_server.py"
    with open(script_path, 'w') as f:
        f.write(script_content)
    return script_path

def deploy_model(deployment_name, venv_path, port):
    if os.name == 'nt':  # Windows
        python_path = os.path.join(venv_path, 'Scripts', 'python')
    else:  # Unix-based systems
        python_path = os.path.join(venv_path, 'bin', 'python')
    
    script_path = create_model_script(deployment_name, port)
    
    cmd = [python_path, script_path]
    
    process = subprocess.Popen(cmd)
    return process

@app.post("/deploy")
def deploy(deployment: ModelDeployment):
    global next_port
    if deployment.deployment_name in deployed_models:
        raise HTTPException(status_code=400, detail="Model already deployed")
    
    if not check_resource_availability():
        raise HTTPException(status_code=503, detail="Insufficient system resources")
    
    current_dir = os.getcwd()
    venv_name = f"venv_{deployment.deployment_name}"
    venv_path = os.path.join(current_dir, venv_name)
    req_file = os.path.join(current_dir, deployment.requirements_file)
    
    if not os.path.exists(req_file):
        raise HTTPException(status_code=404, detail=f"Requirements file {deployment.requirements_file} not found")
    
    create_venv(venv_path)
    install_requirements(venv_path, req_file)
    
    port = next_port
    process = deploy_model(deployment.deployment_name, venv_path, port)
    
    deployed_models[deployment.deployment_name] = {"process": process, "port": port}
    next_port += 1
    
    return {"message": f"Model {deployment.deployment_name} deployed on port {port}"}

@app.get("/status")
def status():
    return {model: {"port": info["port"]} for model, info in deployed_models.items()}

@app.post("/undeploy/{deployment_name}")
def undeploy(deployment_name: str):
    if deployment_name not in deployed_models:
        raise HTTPException(status_code=404, detail="Model not found")
    
    process = deployed_models[deployment_name]["process"]
    process.terminate()
    process.wait()
    
    del deployed_models[deployment_name]
    
    return {"message": f"Model {deployment_name} undeployed"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)