import os
import subprocess
import time
from flask import jsonify
from dotenv import load_dotenv
import json

load_dotenv()  # Load environment variables

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
EKS_CLUSTER_NAME = os.getenv("EKS_CLUSTER_NAME")
EKS_CACHE_DURATION = int(os.getenv("EKS_CACHE_DURATION", 300))  # Default 5 minutes

last_configured_time = 0

def configure_eks_cluster():
    global last_configured_time
    current_time = time.time()
    if current_time - last_configured_time < EKS_CACHE_DURATION:
        return True

    try:
        os.environ["AWS_ACCESS_KEY_ID"] = AWS_ACCESS_KEY_ID
        os.environ["AWS_SECRET_ACCESS_KEY"] = AWS_SECRET_ACCESS_KEY
        os.environ["AWS_DEFAULT_REGION"] = AWS_REGION

        command = f"aws eks update-kubeconfig --region {AWS_REGION} --name {EKS_CLUSTER_NAME} --kubeconfig /tmp/eks-kubeconfig"
        subprocess.check_output(command, shell=True, text=True)
        
        last_configured_time = current_time
        return True
    except subprocess.CalledProcessError:
        return False

def run_kubectl(command):
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


def run_kubectl_command(command):
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500

    try:
        kubeconfig_path = "/tmp/eks-kubeconfig"
        if "pods" in command:
            pods_command = f"KUBECONFIG={kubeconfig_path} kubectl get pods --all-namespaces -o json"
            top_command = f"KUBECONFIG={kubeconfig_path} kubectl top pods --all-namespaces --no-headers"
            limits_command = f"KUBECONFIG={kubeconfig_path} kubectl get pods --all-namespaces -o json"

            pods_output = subprocess.check_output(pods_command, shell=True, text=True).strip()
            top_output = subprocess.check_output(top_command, shell=True, text=True).strip()
            limits_output = subprocess.check_output(limits_command, shell=True, text=True).strip()

            return jsonify(parse_pods_with_usage_and_limits(pods_output, top_output, limits_output)), 200
    except subprocess.CalledProcessError as e:
        return jsonify({"error": str(e)}), 500

def parse_pods_with_usage_and_limits(pods_output, top_output, limits_output):
    pods_data = json.loads(pods_output)
    top_lines = top_output.strip().split("\n")
    limits_data = json.loads(limits_output)

    usage_data = {}
    for line in top_lines:
        columns = line.split()
        namespace, pod_name, cpu, memory = columns[0], columns[1], columns[2], columns[3]
        usage_data[(namespace, pod_name)] = {"CPU": cpu, "Memory": memory}

    pods_info = []

    for pod in pods_data["items"]:
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]
        status = pod["status"]["phase"]
        restarts = sum(int(c["restartCount"]) for c in pod.get("status", {}).get("containerStatuses", []))
        node = pod.get("spec", {}).get("nodeName", "<none>")
        ip = pod.get("status", {}).get("podIP", "<none>")
        age = pod.get("metadata", {}).get("creationTimestamp", "<unknown>")
        ready = f"{sum(1 for c in pod.get('status', {}).get('containerStatuses', []) if c['ready'])}/{len(pod.get('status', {}).get('containerStatuses', []))}"
        containers = pod.get("spec", {}).get("containers", [])

        # Calculate CPU/Memory Usage Percentage
        usage = usage_data.get((namespace, pod_name), {"CPU": "N/A", "Memory": "N/A"})
        cpu_usage = usage["CPU"]
        memory_usage = usage["Memory"]

        cpu_limit, memory_limit = calculate_limits(containers)
        cpu_percentage = calculate_percentage(cpu_usage, cpu_limit)
        memory_percentage = calculate_percentage(memory_usage, memory_limit)

        pods_info.append({
            "NAME": pod_name,
            "NAMESPACE": namespace,
            "STATUS": status,
            "RESTARTS": restarts,
            "NODE": node,
            "IP": ip,
            "AGE": age,
            "READY": ready,
            "CPU": f"{cpu_usage} ({cpu_percentage}%)",
            "MEMORY": f"{memory_usage} ({memory_percentage}%)"
        })

    return {"success": True, "data": pods_info}

def calculate_limits(containers):
    cpu_limit = 0
    memory_limit = 0
    for container in containers:
        resources = container.get("resources", {})
        limits = resources.get("limits", {})
        cpu_limit += parse_cpu(limits.get("cpu", "0"))
        memory_limit += parse_memory(limits.get("memory", "0"))
    return cpu_limit, memory_limit

def calculate_percentage(usage, limit):
    if "N/A" in usage or limit == 0:
        return "N/A"
    
    if "m" in usage:
        usage_value = int(usage.replace("m", ""))
        usage_value /= 1000  # Convert millicores to cores
    else:
        usage_value = float(usage.replace("Mi", "").replace("Gi", ""))

    return round((usage_value / limit) * 100, 2)

def parse_cpu(cpu):
    if not cpu:
        return 0
    if "m" in cpu:
        return int(cpu.replace("m", "")) / 1000
    else:
        return float(cpu)

def parse_memory(memory):
    if not memory:
        return 0
    if "Mi" in memory:
        return float(memory.replace("Mi", ""))
    elif "Gi" in memory:
        return float(memory.replace("Gi", "")) * 1024
    else:
        return 0
