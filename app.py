import os
import subprocess
import time
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import json
from concurrent.futures import ThreadPoolExecutor
from kubernetes_service import run_kubectl

load_dotenv()  # Load environment variables

app = Flask(__name__)
# CORS(app)

# Kubernetes API Endpoints
@app.route("/api/k8s/pods", methods=["GET"])
def get_pods():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("get pods --all-namespaces -o wide")

@app.route("/api/k8s/nodes", methods=["GET"])
def get_nodes():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl("get nodes --all-namespaces")

@app.route("/api/k8s/pods-usage", methods=["GET"])
def get_pods_with_usage():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("get pods --all-namespaces")

@app.route("/api/k8s/stats", methods=["GET"])
def get_k8s_stats():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500

    # Run all kubectl commands in parallel for faster response
    with ThreadPoolExecutor() as executor:
        futures = {
            "namespaces": executor.submit(get_resource_count, "namespaces"),
            "nodes": executor.submit(get_resource_count, "nodes"),
            "deployments": executor.submit(get_resource_count, "deployments"),
            "pods": executor.submit(get_resource_count, "pods"),
            "containers": executor.submit(get_pod_container_count),
            "replicasets": executor.submit(get_resource_count, "replicasets"),
            "services": executor.submit(get_resource_count, "services"),
            "daemonsets": executor.submit(get_resource_count, "daemonsets"),
            "cronjobs": executor.submit(get_resource_count, "cronjobs"),
            "jobs": executor.submit(get_resource_count, "jobs"),
            "statefulsets": executor.submit(get_resource_count, "statefulsets"),
            "hpas": executor.submit(get_resource_count, "horizontalpodautoscalers"),
            "vpas": executor.submit(get_resource_count, "verticalpodautoscalers"),
            "crds": executor.submit(get_resource_count, "customresourcedefinitions"),
            "crs": executor.submit(get_resource_count, "clusterroles")
        }

        stats = {
            "clusters": 1,  # We are monitoring a single cluster
        }

        # Collect results from parallel execution
        for key, future in futures.items():
            stats[key] = future.result()

    return jsonify(stats)

def get_resource_count(resource):
    """
    Get the count of a specific Kubernetes resource.
    """
    kubeconfig_path = "/tmp/eks-kubeconfig"
    try:
        output = subprocess.check_output(
            f"KUBECONFIG={kubeconfig_path} kubectl get {resource} --all-namespaces --no-headers | wc -l",
            shell=True, text=True
        ).strip()
        return int(output)
    except subprocess.CalledProcessError:
        return 0

def get_pod_container_count():
    """
    Get the total number of containers across all pods in all namespaces.
    """
    kubeconfig_path = "/tmp/eks-kubeconfig"
    try:
        output = subprocess.check_output(
            f"KUBECONFIG={kubeconfig_path} kubectl get pods --all-namespaces -o jsonpath='{{range .items[*]}}{{range .spec.containers[*]}}1{{\"\\n\"}}{{end}}{{end}}' | wc -l",
            shell=True, text=True
        ).strip()
        return int(output)
    except subprocess.CalledProcessError:
        return 0

def configure_eks_cluster():
    try:
        command = f"aws eks update-kubeconfig --region {os.getenv('AWS_REGION')} --name {os.getenv('EKS_CLUSTER_NAME')} --kubeconfig /tmp/eks-kubeconfig"
        subprocess.check_output(command, shell=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False

def run_kubectl_command(command):
    try:
        kubeconfig_path = "/tmp/eks-kubeconfig"
        if "pods" in command:
            pods_command = f"KUBECONFIG={kubeconfig_path} kubectl get pods --all-namespaces -o json"
            top_command = f"KUBECONFIG={kubeconfig_path} kubectl top pods --all-namespaces --no-headers"
            
            pods_output = subprocess.check_output(pods_command, shell=True, text=True).strip()
            top_output = subprocess.check_output(top_command, shell=True, text=True).strip()

            return jsonify(parse_pods_with_usage_and_limits(pods_output, top_output)), 200
        else:
            output = subprocess.check_output(f"KUBECONFIG={kubeconfig_path} kubectl {command}", shell=True, text=True)
            return jsonify({"success": True, "data": output}), 200
    except subprocess.CalledProcessError as e:
        return jsonify({"error": str(e)}), 500

def parse_pods_with_usage_and_limits(pods_output, top_output):
    pods_data = json.loads(pods_output)
    top_lines = top_output.strip().split("\n")

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
        
        # Usage Values
        usage = usage_data.get((namespace, pod_name), {"CPU": "N/A", "Memory": "N/A"})
        cpu_usage = usage["CPU"]
        memory_usage = usage["Memory"]

        cpu_percentage = calculate_cpu_percentage(cpu_usage)
        memory_percentage = calculate_memory_percentage(memory_usage)

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

def calculate_cpu_percentage(cpu_usage):
    if "m" in cpu_usage:
        cpu_value = int(cpu_usage.replace("m", ""))
        return round((cpu_value / 1000) * 100, 2)  # Assuming 1 CPU (1000m) as 100%
    elif "N/A" in cpu_usage:
        return "N/A"
    else:
        return 0.0

def calculate_memory_percentage(memory_usage):
    if "Mi" in memory_usage:
        memory_value = int(memory_usage.replace("Mi", ""))
        return round((memory_value / 1024) * 100, 2)  # Assuming 1Gi as 100%
    elif "Gi" in memory_usage:
        memory_value = float(memory_usage.replace("Gi", ""))
        return round(memory_value * 100, 2)
    elif "N/A" in memory_usage:
        return "N/A"
    else:
        return 0.0

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
