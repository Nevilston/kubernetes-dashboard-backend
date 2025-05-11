import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from kubernetes_service import run_kubectl_command, configure_eks_cluster
from cost_service import get_cluster_cost  
from concurrent.futures import ThreadPoolExecutor

load_dotenv()  # Load environment variables

app = Flask(__name__)
CORS(app)

# Kubernetes API Endpoints
@app.route("/api/k8s/pods", methods=["GET"])
def get_pods():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("get pods --all-namespaces")

@app.route("/api/k8s/nodes", methods=["GET"])
def get_nodes():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("get nodes --all-namespaces")

@app.route("/api/k8s/deployments", methods=["GET"])
def get_deployments():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("get deployments --all-namespaces")

@app.route("/api/k8s/top-nodes", methods=["GET"])
def get_top_nodes():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    return run_kubectl_command("top nodes")

# Cost Calculation API
@app.route("/api/k8s/cost", methods=["GET"])
def get_cluster_cost_api():
    if not configure_eks_cluster():
        return jsonify({"error": "Failed to connect to EKS Cluster"}), 500
    cost_data = get_cluster_cost()
    return jsonify(cost_data)

# Dashboard Statistics API
import os
import subprocess
import time
from flask import jsonify
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()  # Load environment variables

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




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
