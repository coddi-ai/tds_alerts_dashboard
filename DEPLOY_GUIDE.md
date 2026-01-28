# 🚀 Deployment Guide - Oil Analysis Dashboard

Complete step-by-step guide to build, test, and deploy the dashboard to production.

## 📋 Pre-Deployment Checklist

- [ ] Docker and Docker Compose installed
- [ ] Git repository access configured
- [ ] Production server access (if deploying remotely)
- [ ] GitHub Personal Access Token (for GHCR) or Docker Hub account
- [ ] Updated data files in `data/oil/processed/`
- [ ] Production environment variables configured

## 🛠️ Phase 1: Local Build & Test

### Step 1.1: Prepare Environment

```bash
# Navigate to project directory
cd alerts_dashboard_production

# Verify all required files exist
ls -la

# Expected files:
# ✓ Dockerfile
# ✓ docker-compose.yml
# ✓ requirements.txt
# ✓ .env
# ✓ dashboard/
# ✓ config/
# ✓ data/oil/processed/
```

### Step 1.2: Validate Data Files

```bash
# Check data files exist
ls -la data/oil/processed/

# Verify JSON is valid
cat data/oil/processed/cda_summary.json | python -m json.tool > /dev/null && echo "✓ Valid JSON" || echo "✗ Invalid JSON"
cat data/oil/processed/emin_summary.json | python -m json.tool > /dev/null && echo "✓ Valid JSON" || echo "✗ Invalid JSON"
cat data/oil/processed/stewart_limits.json | python -m json.tool > /dev/null && echo "✓ Valid JSON" || echo "✗ Invalid JSON"
```

### Step 1.3: Build Docker Image

```bash
# Build with tag
docker build -t oil-dashboard:test .

# Monitor build process
# Expected: All layers build successfully, no errors

# Verify image created
docker images | grep oil-dashboard

# Expected output:
# oil-dashboard    test    <image-id>    <time>    <size>
```

**Build Troubleshooting:**
```bash
# If build fails, check Dockerfile syntax
docker build --no-cache -t oil-dashboard:test .

# View detailed build output
docker build --progress=plain -t oil-dashboard:test .
```

### Step 1.4: Run Local Test Container

```bash
# Start test container
docker run -d \
  --name oil-dashboard-test \
  -p 8050:8050 \
  -v "$(pwd)/data:/app/data:ro" \
  -v "$(pwd)/logs:/app/logs" \
  -e SECRET_KEY=test-local-secret-key-12345 \
  oil-dashboard:test

# Verify container is running
docker ps | grep oil-dashboard-test

# Expected: STATUS shows "Up X seconds"
```

### Step 1.5: Monitor Container Health

```bash
# View real-time logs
docker logs -f oil-dashboard-test

# Expected output:
# Dash is running on http://0.0.0.0:8050/
# * Serving Flask app 'app'
# * Running on http://0.0.0.0:8050

# Check container stats
docker stats oil-dashboard-test --no-stream

# Press Ctrl+C to stop following logs
```

### Step 1.6: Test Dashboard Functionality

**Automated Health Check:**
```bash
# Test HTTP response
curl -I http://localhost:8050

# Expected: HTTP/1.1 200 OK

# Test with detailed response
curl http://localhost:8050 | grep -i "dash"
```

**Manual Testing:**
1. Open browser: `http://localhost:8050`
2. **Login Test**:
   - Username: `admin`
   - Password: `admin123`
   - ✓ Should redirect to dashboard
3. **Tab Verification**:
   - ✓ Machines tab loads
   - ✓ Limits tab loads
   - ✓ Reports tab loads
4. **Data Display**:
   - ✓ Machine list populates
   - ✓ Charts render correctly
   - ✓ Filters work
   - ✓ Tables display data
5. **Console Check**:
   - Open DevTools (F12)
   - ✓ No JavaScript errors
   - ✓ No 404 resources

### Step 1.7: Cleanup Test Container

```bash
# Stop test container
docker stop oil-dashboard-test

# Remove test container
docker rm oil-dashboard-test

# Verify removal
docker ps -a | grep oil-dashboard-test
# Expected: No output
```

## 🧪 Phase 2: Docker Compose Test

### Step 2.1: Test with Docker Compose

```bash
# Start with docker-compose
docker-compose up

# Watch logs in terminal
# Expected: Dashboard starts successfully

# In another terminal, test connection
curl http://localhost:8050

# Stop with Ctrl+C, then cleanup
docker-compose down
```

### Step 2.2: Test Background Mode

```bash
# Start in detached mode
docker-compose up -d

# Verify service is running
docker-compose ps

# Expected output:
# NAME                    SERVICE      STATUS       PORTS
# oil-analysis-dashboard  dashboard    running      0.0.0.0:8050->8050/tcp

# View logs
docker-compose logs -f

# Test dashboard access
# Open http://localhost:8050 in browser

# Stop when testing complete
docker-compose down
```

## 📦 Phase 3: Prepare for Production

### Step 3.1: Create Production Tag

```bash
# Tag image with version
docker tag oil-dashboard:test oil-dashboard:v1.0.0
docker tag oil-dashboard:test oil-dashboard:latest

# Verify tags
docker images | grep oil-dashboard

# Expected: Multiple tags for same IMAGE ID
```

### Step 3.2: Configure Production Environment

```bash
# Create production env file
cat > .env.production << 'EOF'
# Production Configuration
SECRET_KEY=CHANGE_THIS_TO_RANDOM_64_CHAR_STRING
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8050
DATA_ROOT=/app/data/oil
LOG_LEVEL=INFO
EOF

# Generate secure SECRET_KEY (Python)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Copy output and update .env.production
```

### Step 3.3: Update Production Credentials

```bash
# Edit user credentials
# Open config/users.py and change default passwords

# Verify changes
cat config/users.py | grep USERS
```

### Step 3.4: Test Production Configuration

```bash
# Test with production env
docker run -d \
  --name oil-dashboard-prod-test \
  -p 8050:8050 \
  --env-file .env.production \
  -v "$(pwd)/data:/app/data:ro" \
  oil-dashboard:v1.0.0

# Test login with new credentials
# Open http://localhost:8050

# Cleanup
docker stop oil-dashboard-prod-test
docker rm oil-dashboard-prod-test
```

## 🌐 Phase 4: Push to Container Registry

### Option A: GitHub Container Registry (Recommended)

#### Step 4A.1: Create GitHub Personal Access Token

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Set:
   - Note: `Docker GHCR Access`
   - Expiration: Custom (1 year)
   - Scopes: ✓ `write:packages`, ✓ `read:packages`, ✓ `delete:packages`
4. Generate and copy token

#### Step 4A.2: Login to GHCR

```bash
# Save token to environment variable (temporary)
export GITHUB_TOKEN=ghp_your_token_here

# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u portizv26 --password-stdin

# Expected: Login Succeeded
```

#### Step 4A.3: Tag for GHCR

```bash
# Tag with GHCR prefix
docker tag oil-dashboard:v1.0.0 ghcr.io/portizv26/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest ghcr.io/portizv26/oil-dashboard:latest

# Verify tags
docker images | grep oil-dashboard
```

#### Step 4A.4: Push to GHCR

```bash
# Push version tag
docker push ghcr.io/portizv26/oil-dashboard:v1.0.0

# Expected: Layers pushed successfully
# The push refers to repository [ghcr.io/portizv26/oil-dashboard]
# v1.0.0: digest: sha256:... size: ...

# Push latest tag
docker push ghcr.io/portizv26/oil-dashboard:latest
```

#### Step 4A.5: Verify on GitHub

1. Go to: `https://github.com/portizv26?tab=packages`
2. Find `oil-dashboard` package
3. ✓ Should show version `v1.0.0` and `latest`

#### Step 4A.6: Make Package Public (Optional)

1. Click on package → Package settings
2. Scroll to "Danger Zone"
3. Click "Change visibility" → Public
4. Confirm

### Option B: Docker Hub

#### Step 4B.1: Login to Docker Hub

```bash
# Login to Docker Hub
docker login

# Enter username and password
# Expected: Login Succeeded
```

#### Step 4B.2: Tag for Docker Hub

```bash
# Replace 'yourusername' with your Docker Hub username
docker tag oil-dashboard:v1.0.0 yourusername/oil-dashboard:v1.0.0
docker tag oil-dashboard:latest yourusername/oil-dashboard:latest
```

#### Step 4B.3: Push to Docker Hub

```bash
# Push images
docker push yourusername/oil-dashboard:v1.0.0
docker push yourusername/oil-dashboard:latest
```

## 🖥️ Phase 5: Deploy to Production Server

### Step 5.1: Prepare Production Server

```bash
# SSH into production server
ssh user@production-server

# Install Docker and Docker Compose (if not installed)
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install -y docker.io docker-compose

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -aG docker $USER

# Logout and login again for group changes
```

### Step 5.2: Pull Image on Production

```bash
# On production server

# Login to registry
echo $GITHUB_TOKEN | docker login ghcr.io -u portizv26 --password-stdin

# Pull latest image
docker pull ghcr.io/portizv26/oil-dashboard:latest

# Verify image
docker images | grep oil-dashboard
```

### Step 5.3: Setup Production Directory

```bash
# Create application directory
mkdir -p ~/oil-dashboard
cd ~/oil-dashboard

# Create data directories
mkdir -p data/oil/processed
mkdir -p logs

# Upload data files (from local machine)
# Use scp, rsync, or git to transfer data files
scp -r data/oil/processed/* user@production-server:~/oil-dashboard/data/oil/processed/
```

### Step 5.4: Create Production Compose File

```bash
# On production server
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  dashboard:
    image: ghcr.io/portizv26/oil-dashboard:latest
    container_name: oil-analysis-dashboard
    restart: unless-stopped
    ports:
      - "8050:8050"
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - DASHBOARD_HOST=0.0.0.0
      - DASHBOARD_PORT=8050
      - DATA_ROOT=/app/data/oil
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/app/data:ro
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8050"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
EOF
```

### Step 5.5: Create Production Environment

```bash
# Create .env file
cat > .env << 'EOF'
SECRET_KEY=your-secure-production-key-here
EOF

# Generate and set secure key
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" > .env
```

### Step 5.6: Start Production Service

```bash
# Start dashboard
docker-compose up -d

# Verify status
docker-compose ps

# Check logs
docker-compose logs -f

# Test local access
curl http://localhost:8050

# Expected: HTML response
```

### Step 5.7: Configure Reverse Proxy (Optional)

**Using Nginx:**
```nginx
# /etc/nginx/sites-available/dashboard
server {
    listen 80;
    server_name dashboard.yourdomain.com;

    location / {
        proxy_pass http://localhost:8050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 📊 Phase 6: Post-Deployment Verification

### Step 6.1: Health Checks

```bash
# Check container health
docker ps

# Verify health status
docker inspect oil-analysis-dashboard | grep -A 5 Health

# Test HTTP endpoint
curl -I http://your-server-ip:8050

# Expected: HTTP/1.1 200 OK
```

### Step 6.2: Monitor Logs

```bash
# View logs
docker-compose logs -f

# Check for errors
docker-compose logs | grep -i error

# Monitor resource usage
docker stats oil-analysis-dashboard
```

### Step 6.3: Functional Testing

1. Access dashboard URL
2. Test login
3. Verify all tabs load
4. Check data displays correctly
5. Test filters and interactions
6. Verify no console errors

## 🔄 Phase 7: Update Workflow

### When Data Changes

```bash
# On local machine, update data files
# Then sync to production
scp data/oil/processed/* user@production:/home/user/oil-dashboard/data/oil/processed/

# On production, restart dashboard
docker-compose restart
```

### When Code Changes

```bash
# On local machine
# 1. Make changes
# 2. Test locally
# 3. Build new image
docker build -t oil-dashboard:v1.1.0 .

# 4. Tag for registry
docker tag oil-dashboard:v1.1.0 ghcr.io/portizv26/oil-dashboard:v1.1.0
docker tag oil-dashboard:v1.1.0 ghcr.io/portizv26/oil-dashboard:latest

# 5. Push to registry
docker push ghcr.io/portizv26/oil-dashboard:v1.1.0
docker push ghcr.io/portizv26/oil-dashboard:latest

# On production server
# 6. Pull new image
docker pull ghcr.io/portizv26/oil-dashboard:latest

# 7. Restart with new image
docker-compose down
docker-compose up -d

# 8. Verify update
docker-compose logs -f
```

## 🚨 Rollback Procedure

```bash
# If something goes wrong, rollback to previous version

# On production server
docker-compose down

# Pull previous version
docker pull ghcr.io/portizv26/oil-dashboard:v1.0.0

# Update docker-compose.yml to use specific version
# Change: image: ghcr.io/portizv26/oil-dashboard:v1.0.0

# Start with old version
docker-compose up -d

# Verify
docker-compose logs -f
```

## ✅ Final Checklist

- [ ] Local build successful
- [ ] Local tests pass
- [ ] Docker Compose test successful
- [ ] Production environment configured
- [ ] Image pushed to registry
- [ ] Production server setup complete
- [ ] Dashboard accessible
- [ ] Login works with production credentials
- [ ] All data displays correctly
- [ ] Logs show no errors
- [ ] Health checks pass
- [ ] Backup procedure documented
- [ ] Team notified of deployment

## 📞 Support

If deployment fails at any step:
1. Check logs: `docker-compose logs`
2. Verify all files present
3. Confirm network/firewall settings
4. Review this guide from failed step
5. Contact DevOps team

---

**Success!** 🎉 Your dashboard is now deployed and ready for production use.
