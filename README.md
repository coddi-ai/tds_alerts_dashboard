# Oil Analysis Dashboard - Production Deployment

Interactive web dashboard for oil analysis and technical alerts monitoring. Built with Dash and Plotly, containerized with Docker for easy deployment.

## 📋 Overview

This dashboard provides:
- **Machine Status Monitoring**: Track oil analysis results across all equipment
- **Limit Management**: Configure and monitor technical limits (Stewart, custom)
- **Automated Reports**: View AI-generated recommendations and alerts
- **Historical Analysis**: Analyze trends and patterns over time

## 🏗️ Architecture

```
alerts_dashboard_production/
├── dashboard/          # Dash application logic
├── config/            # Application configuration
├── data/
│   └── oil/
│       └── processed/ # Pre-processed JSON data files
├── documentation/     # Technical documentation
├── Dockerfile         # Container definition
├── docker-compose.yml # Docker Compose orchestration
├── requirements.txt   # Python dependencies
└── .env              # Environment configuration
```

## 🔧 Prerequisites

- **Docker**: Version 20.10 or higher
- **Docker Compose**: Version 2.0 or higher
- Git (for cloning repository)

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/portizv26/Multi-Technical-Alerts.git
cd Multi-Technical-Alerts/alerts_dashboard_production
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env .env.local

# Edit configuration (optional)
# Set SECRET_KEY for production
```

### 3. Run with Docker Compose

```bash
# Build and start the dashboard
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the dashboard
docker-compose down
```

### 4. Access Dashboard

Open your browser and navigate to:
```
http://localhost:8050
```

**Default Credentials:**
- Username: `admin`
- Password: `admin123` (change in production via `config/users.py`)

## 📦 Deployment Guide

### Local Testing Before Production

#### Step 1: Build Docker Image

```bash
# Build the image locally
docker build -t oil-dashboard:latest .

# Verify image was created
docker images | grep oil-dashboard
```

#### Step 2: Test Image Locally

```bash
# Run container with volume mount
docker run -d \
  --name oil-dashboard-test \
  -p 8050:8050 \
  -v $(pwd)/data:/app/data:ro \
  -v $(pwd)/logs:/app/logs \
  -e SECRET_KEY=test-secret-key \
  oil-dashboard:latest

# Check container logs
docker logs -f oil-dashboard-test

# Test the dashboard
curl http://localhost:8050

# Stop and remove test container
docker stop oil-dashboard-test
docker rm oil-dashboard-test
```

#### Step 3: Run Integration Tests

```bash
# Test with Docker Compose (recommended)
docker-compose up

# Open browser to http://localhost:8050
# Verify:
# ✓ Login page loads
# ✓ Authentication works
# ✓ All tabs render correctly
# ✓ Charts display data
# ✓ Filters work properly
# ✓ No console errors

# Stop when testing is complete
docker-compose down
```

#### Step 4: Tag Image for Registry

```bash
# Tag for Docker Hub
docker tag oil-dashboard:latest yourusername/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest yourusername/oil-dashboard:latest

# Or tag for GitHub Container Registry
docker tag oil-dashboard:latest ghcr.io/portizv26/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest ghcr.io/portizv26/oil-dashboard:latest
```

#### Step 5: Push to Registry

**Option A: Docker Hub**
```bash
# Login to Docker Hub
docker login

# Push images
docker push yourusername/oil-dashboard:v1.0.0
docker push yourusername/oil-dashboard:latest
```

**Option B: GitHub Container Registry**
```bash
# Create GitHub Personal Access Token (PAT) with write:packages scope
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u portizv26 --password-stdin

# Push images
docker push ghcr.io/portizv26/oil-dashboard:v1.0.0
docker push ghcr.io/portizv26/oil-dashboard:latest
```

#### Step 6: Deploy to Production Server

```bash
# On production server, pull the image
docker pull ghcr.io/portizv26/oil-dashboard:latest

# Create production docker-compose.yml
# Set environment variables
# Start the service
docker-compose -f docker-compose.prod.yml up -d
```

## 🔐 Production Configuration

### Environment Variables

Create a `.env` file for production:

```bash
# Security
SECRET_KEY=your-production-secret-key-here-min-32-chars

# Server Configuration
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8050

# Data
DATA_ROOT=/app/data/oil

# Optional: Logging
LOG_LEVEL=INFO
```

### Update User Credentials

Edit `config/users.py` and update default passwords:

```python
USERS = {
    "admin": "your-secure-password-here",
    "viewer": "another-secure-password"
}
```

### Data Updates

To update dashboard data:

```bash
# Replace processed data files
cp new_cda_summary.json data/oil/processed/
cp new_emin_summary.json data/oil/processed/
cp new_stewart_limits.json data/oil/processed/

# Restart dashboard
docker-compose restart
```

## 🐳 Docker Commands Reference

### Build & Run
```bash
# Build image
docker build -t oil-dashboard .

# Run container
docker run -d -p 8050:8050 --name dashboard oil-dashboard

# Run with docker-compose
docker-compose up -d
```

### Management
```bash
# View logs
docker logs -f oil-dashboard
docker-compose logs -f

# Stop containers
docker stop oil-dashboard
docker-compose down

# Restart containers
docker restart oil-dashboard
docker-compose restart

# Remove containers
docker rm oil-dashboard
docker-compose down -v
```

### Debugging
```bash
# Access container shell
docker exec -it oil-dashboard bash

# Inspect container
docker inspect oil-dashboard

# View resource usage
docker stats oil-dashboard
```

## 📊 Data Format

The dashboard expects processed data in JSON format:

- `data/oil/processed/cda_summary.json` - CDA lab results
- `data/oil/processed/emin_summary.json` - EMIN lab results  
- `data/oil/processed/stewart_limits.json` - Stewart limit definitions

See `documentation/data_contracts.md` for detailed schemas.

## 🔍 Troubleshooting

### Dashboard Won't Start

```bash
# Check logs
docker-compose logs

# Verify data files exist
ls -la data/oil/processed/

# Check port availability
netstat -an | grep 8050
```

### Login Issues

- Verify credentials in `config/users.py`
- Check SECRET_KEY is set in `.env`
- Clear browser cache and cookies

### No Data Displayed

- Ensure JSON files are in `data/oil/processed/`
- Verify JSON format is valid
- Check container has read access to data volume

### Performance Issues

```bash
# Increase container resources in docker-compose.yml
services:
  dashboard:
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
```

## 📝 Maintenance

### Update Dependencies

```bash
# Update requirements.txt
# Rebuild image
docker-compose build --no-cache

# Restart services
docker-compose up -d
```

### Backup Data

```bash
# Backup processed data
tar -czf dashboard-data-backup-$(date +%Y%m%d).tar.gz data/

# Backup logs
tar -czf dashboard-logs-backup-$(date +%Y%m%d).tar.gz logs/
```

## 📚 Additional Documentation

- `documentation/dashboard_documentation.md` - Dashboard features and usage
- `documentation/data_contracts.md` - Data format specifications
- `documentation/deployment_guide_for_dummies.md` - Detailed deployment guide

## 🤝 Support

For issues or questions:
1. Check troubleshooting section above
2. Review application logs: `docker-compose logs`
3. Contact development team

## 📄 License

Internal use only - Proprietary software

---

**Version**: 1.0.0  
**Last Updated**: January 2026  
**Maintained by**: Technical Alerts Team
