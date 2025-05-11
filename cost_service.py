import os
import boto3
import subprocess
from datetime import datetime, timezone
from dotenv import load_dotenv
from kubernetes_service import configure_eks_cluster  # Use the existing function

load_dotenv()  # Load environment variables

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")

def get_cluster_cost():
    try:
        if not configure_eks_cluster():
            return {"error": "Failed to connect to EKS Cluster"}

        # Get list of node instance IDs
        kubeconfig_path = "/tmp/eks-kubeconfig"
        nodes_output = subprocess.check_output(
            f"KUBECONFIG={kubeconfig_path} kubectl get nodes -o jsonpath='{{.items[*].spec.providerID}}'",
            shell=True, text=True
        )
        instance_ids = [id.split('/')[-1] for id in nodes_output.strip().split()]

        # Initialize AWS clients
        ec2 = boto3.client('ec2')
        pricing = boto3.client('pricing', region_name='us-east-1')  # Pricing API is in us-east-1

        total_cost = 0.0
        node_costs = []

        # Describe instances to get launch times and instance types
        reservations = ec2.describe_instances(InstanceIds=instance_ids)['Reservations']
        for reservation in reservations:
            for instance in reservation['Instances']:
                instance_id = instance['InstanceId']
                instance_type = instance['InstanceType']
                launch_time = instance['LaunchTime']

                # Calculate uptime in hours
                now = datetime.now(timezone.utc)
                uptime = (now - launch_time).total_seconds() / 3600

                # Get pricing information
                price_per_hour = get_instance_price(instance_type)
                cost = price_per_hour * uptime
                total_cost += cost
                node_costs.append({
                    "instance_id": instance_id,
                    "instance_type": instance_type,
                    "uptime_hours": round(uptime, 2),
                    "hourly_cost": round(price_per_hour, 4),
                    "total_cost": round(cost, 4)
                })

        # Add EKS control plane cost ($0.10/hour)
        control_plane_cost_per_hour = 0.10
        cluster_uptime_hours = max(node['uptime_hours'] for node in node_costs) if node_costs else 0
        control_plane_cost = control_plane_cost_per_hour * cluster_uptime_hours
        total_cost += control_plane_cost

        return {
            "total_running_cost": round(total_cost, 4),
            "control_plane_cost": round(control_plane_cost, 4),
            "nodes": node_costs
        }

    except Exception as e:
        return {"error": str(e)}

def get_instance_price(instance_type):
    pricing = boto3.client('pricing', region_name='us-east-1')
    response = pricing.get_products(
        ServiceCode='AmazonEC2',
        Filters=[
            {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': instance_type},
            {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': 'EU (Frankfurt)'},
            {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'}
        ],
        MaxResults=1
    )
    price_list = response['PriceList']
    for price_item in price_list:
        price_data = eval(price_item)
        terms = price_data.get("terms", {}).get("OnDemand", {})
        for term in terms.values():
            for price_dimension in term["priceDimensions"].values():
                return float(price_dimension["pricePerUnit"]["USD"])
    return 0.0
