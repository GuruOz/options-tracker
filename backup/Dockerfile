# syntax=docker/dockerfile:1

# postgres:16-alpine plus `age` for optional client-side backup encryption.
FROM postgres:18-alpine
RUN apk add --no-cache age

# trivy:ignore:AVD-DS-0002
# Deliberately root, not a Dockerfile oversight: ./backups is a host bind
# mount (so an operator can browse/rsync it directly), and Docker creates
# that directory root-owned on first run. A fixed non-root uid here can't
# reliably write to it across "fresh clone" and "pre-existing deployment"
# without an ownership-fixing entrypoint step this container doesn't need
# otherwise. It never runs the postgres server (docker-compose.yml overrides
# the entrypoint with a pg_dump/age loop only) and already runs with
# cap_drop: [ALL] + no-new-privileges in docker-compose.yml, which covers the
# realistic blast radius for a container that only shells out to pg_dump/age
# against its own database - see docs/SECURITY.md's accepted-risk register.
