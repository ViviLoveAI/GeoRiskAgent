# EC2 Deployment

This guide describes a lightweight single-instance AWS EC2 deployment for GeoRisk Transmission Analyzer.

The deployment runs two Docker Compose services on one Ubuntu server:

- FastAPI backend on port `8000`
- Streamlit UI on port `8501`

This is intended as a simple portfolio-ready deployment path. It is not a production hardening guide.

## Recommended EC2 Configuration

- AMI: Ubuntu Server 22.04 LTS or Ubuntu Server 24.04 LTS
- Instance type: `t3.medium` recommended
- Storage: 20-30 GB EBS volume
- Security Group:
  - SSH `22`: allow from your IP only
  - FastAPI `8000`: allow from your IP or the intended demo audience
  - Streamlit `8501`: allow from your IP or the intended demo audience

Do not store AWS credentials, GitHub tokens, SSH private keys, or `.env` secrets in the repository.

## 1. Launch the EC2 Instance

Create an Ubuntu EC2 instance with the recommended configuration above.

After launch, SSH into the instance:

```bash
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP>
```

## 2. Install Docker

From the project repository, you can use the helper script:

```bash
bash scripts/setup_ec2_docker.sh
```

The script installs basic packages, installs Docker using Docker's official convenience script, and adds the `ubuntu` user to the `docker` group.

After the script finishes, log out and SSH back in so the Docker group change takes effect:

```bash
exit
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP>
```

Verify Docker:

```bash
docker --version
docker compose version
```

## 3. Clone the Repository

Clone your GitHub repository onto the EC2 instance:

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

## 4. Configure Environment Variables

Create a `.env` file manually if you want to use the optional LLM Event Analyst.

Example keys to define locally:

```bash
OPENAI_API_KEY=...
USE_LLM_EVENT_ANALYST=true
LLM_EVENT_ANALYST_MODEL=gpt-4.1-mini
```

Do not commit `.env` or paste secret values into documentation.

If you do not configure an API key, the system can still run with the rule-based Event Analyst fallback.

## 5. Start the App

Build and run both services:

```bash
docker compose up --build -d
```

Check containers:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f
```

## 6. Open the Services

Streamlit UI:

```text
http://<EC2_PUBLIC_IP>:8501
```

FastAPI docs:

```text
http://<EC2_PUBLIC_IP>:8000/docs
```

FastAPI health check:

```text
http://<EC2_PUBLIC_IP>:8000/health
```

## 7. Check Deployment Health

From the EC2 instance:

```bash
bash scripts/check_deployment.sh
```

From your local machine:

```bash
bash scripts/check_deployment.sh http://<EC2_PUBLIC_IP>:8000
```

Expected result:

```text
FastAPI backend reachable
```

## 8. Stop the App

```bash
docker compose down
```

## Notes and Limitations

- This setup exposes app ports directly from a single EC2 instance.
- For a production deployment, add HTTPS, authentication, monitoring, backups, and stricter network controls.
- Restrict open ports to your IP when possible.
- The project generates risk watchlists and evidence-grounded exposure analysis. It does not provide investment advice.
