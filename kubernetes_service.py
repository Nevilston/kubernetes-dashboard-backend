import os
import subprocess
import time
from flask import jsonify
from dotenv import load_dotenv

load_dotenv()  # Load environment variables

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME")
EKS_CACHE_DURATION = int(os.getenv("EKS_CACHE_DURATION", 300))  # Default 5 minutes

# Cache variables
last_configured_time = 0

def configure_eks_cluster():
    global last_configured_time

    # Check if cached configuration is still valid
    current_time = time.time()
    if current_time - last_configured_time < EKS_CACHE_DURATION:
        print(f"✅ Using cached EKS Configuration: {EKS_CLUSTER_NAME}")
        return True

    try:
        # Set AWS environment variables directly
        os.environ["AWS_ACCESS_KEY_ID"] = AWS_ACCESS_KEY_ID
        os.environ["AWS_SECRET_ACCESS_KEY"] = AWS_SECRET_ACCESS_KEY
        os.environ["AWS_DEFAULT_REGION"] = AWS_REGION

        # Using AWS CLI to configure kubeconfig
        command = f"aws eks update-kubeconfig --region {AWS_REGION} --name {EKS_CLUSTER_NAME} --kubeconfig /tmp/eks-kubeconfig"
        subprocess.check_output(command, shell=True, text=True)
        
        # Update the last configured time
        last_configured_time = current_time
        print(f"✅ Connected to EKS Cluster: {EKS_CLUSTER_NAME} (Configuration Cached)")

        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to configure EKS: {str(e)}")
        return False

def run_kubectl_command(command):
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500

    try:
        # Optimize for faster response
        kubeconfig_path = "/tmp/eks-kubeconfig"
        if "pods" in command:
            # Optimized command for counting running containers
            optimized_command = f"KUBECONFIG={kubeconfig_path} kubectl get pods --all-namespaces -o jsonpath='{{range .items[*]}}{{range .status.containerStatuses[*]}}{{.state.running}}{{\"\\n\"}}{{end}}{{end}}' | wc -l"
            output = subprocess.check_output(optimized_command, shell=True, text=True).strip()
            return jsonify({"running_containers": int(output)}), 200
        
        # For other commands, use the standard kubectl
        output = subprocess.check_output(
            f"KUBECONFIG={kubeconfig_path} kubectl {command} --all-namespaces -o wide",
            shell=True, text=True
        )
        return jsonify(parse_kubectl_output(output)), 200

    except subprocess.CalledProcessError as e:
        return jsonify({"error": str(e)}), 500

def parse_kubectl_output(output):
    """
    Parses the raw kubectl command output into a structured JSON response.
    """
    lines = output.strip().split("\n")
    headers = lines[0].split()
    data_rows = [line.split() for line in lines[1:]]

    parsed_data = [dict(zip(headers, row)) for row in data_rows]
    return {
        "success": True,
        "data": parsed_data
    }
