# Deploying WCC Launchpad

The production setup is the same `docker compose` stack you run locally,
plus **Caddy** in front for automatic, free HTTPS (Let's Encrypt). One small
Linux server is enough.

## 1. Get a server

Any Ubuntu 22.04 or 24.04 machine with **2 GB RAM or more** and a public IP.

| Option | Notes |
|---|---|
| **AWS EC2** (what the live demo runs on) | Ubuntu 24.04, `c7i-flex.large` (2 vCPU, 4 GB), 25 GB disk. Allow SSH, HTTP and HTTPS in the launch form, then attach an Elastic IP so the address never changes. New accounts' free-plan credit covers it. |
| **DigitalOcean Droplet** | Ubuntu 24.04, Basic, 2 GB. Pick the **Bangalore** region for Indian visitors. Billed hourly; destroy it after judging. The GitHub Student Developer Pack includes DigitalOcean credit. |
| AWS Lightsail | Mumbai region, 2 GB plan. |
| Azure for Students | Free credit with a student email, no card needed. Ubuntu VM, size B2s or larger. |
| Hetzner Cloud | Cheapest per GB of RAM; Europe/US only (fine for a demo). |

Whatever you pick, allow inbound ports **22, 80 and 443** in the provider's
firewall if it has one (the setup script configures the server's own).

## 2. Put the code on the server

From your computer (replace the IP; on AWS the user is `ubuntu`, on most
other providers it's `root`):

```bash
scp -i your-key.pem wcc-launchpad.zip .env ubuntu@203.0.113.7:~
ssh -i your-key.pem ubuntu@203.0.113.7
sudo apt-get update && sudo apt-get install -y unzip
unzip wcc-launchpad.zip && cp ~/.env wcc-launchpad/.env && cd wcc-launchpad
```

(Or `git clone` your repository.) Copying your working `.env`, with your
SendGrid key and `GITHUB_TOKEN`, is optional; the script keeps your values
and fills in the rest.

## 3. Run the setup script

```bash
sudo bash deploy/setup-server.sh
```

With no argument it uses a free address like `203-0-113-7.sslip.io`, which
needs no DNS setup and gets a real HTTPS certificate. To use your own domain
(e.g. the free .xyz from the sponsor), first create a DNS **A record**
pointing it to the server's IP, then:

```bash
sudo bash deploy/setup-server.sh launchpad.yourdomain.xyz
```

The script installs Docker, adds swap, enables the firewall, writes the
production settings into `.env` (domain, `PUBLIC_BASE_URL`, a strong
`JWT_SECRET` and database password, nginx bound to localhost), builds and
starts everything, waits for HTTPS, and prints your live URL plus the demo
logins.

## 4. Turn on email

Edit `.env` on the server:

```
MAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=SG.xxxx
MAIL_FROM=WCC Launchpad <your-verified-sender@...>
GITHUB_TOKEN=ghp_xxxx        # optional: code check at full speed
```

Then re-run `sudo bash deploy/setup-server.sh` (safe to repeat). Links in
emails and certificate QR codes now point to your public URL.

## Day-to-day

| Task | Command (in the project folder) |
|---|---|
| See logs | `docker compose logs -f backend` |
| Restart | `docker compose -f docker-compose.yml -f docker-compose.prod.yml restart` |
| Deploy new code | upload or `git pull`, then re-run the setup script |
| Stop | `docker compose -f docker-compose.yml -f docker-compose.prod.yml down` |
| Wipe all data and start fresh | `... down -v`, then re-run the script |

## Before sharing the URL

- **Demo accounts are public knowledge** (password `DemoPass123!`). That's
  deliberate, so judges can try every role. Anyone can also edit the demo
  data, though, so wipe and re-seed after judging, or before a real event.
- The **bootstrap invite codes** are printed only in the server logs; for a
  real event, create fresh expiring invites from the Judging panel instead.
- `JWT_SECRET` signs logins and certificates. Don't change it after issuing
  certificates, or they'll stop verifying.

## How HTTPS and visitor IPs work

Visitor → **Caddy** (HTTPS, port 443) → **nginx** (localhost only) →
backend. Caddy replaces any `X-Forwarded-For` a visitor sends with their real
address. nginx trusts that header only from private addresses (Caddy and
Docker), so the backend sees each visitor's true IP. Vote rate limits and
shared-address detection depend on this. A visitor can't fake a new IP per
vote, whether through Caddy or by hitting nginx directly. WebSocket live
updates pass through both proxies.

## Troubleshooting

- **No HTTPS after the script finishes:** the domain's DNS must point to
  this server, and ports 80 and 443 must be open in the provider's
  firewall. Then check `docker compose logs caddy`.
- **Build killed or very slow:** the server has too little RAM. Use 2 GB or
  more; the script already adds swap.
- **`docker compose` says DOMAIN is not set:** you ran the production
  command without the script; set `DOMAIN=` in `.env`.
