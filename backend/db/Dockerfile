FROM postgres:16

# Our init scripts are COPYed into the image and chmod'd here, at BUILD
# time, rather than bind-mounted from the host at runtime. This is a
# deliberate fix for a real, reproduced bug: Docker Desktop's host
# bind-mount translation (VirtioFS / gRPC-FUSE on macOS, similar issues
# reported on Windows) can misreport a bind-mounted script's executable
# bit -- the container sees `+x`, Postgres's entrypoint decides to exec
# it directly via its shebang, and the kernel still fails to invoke the
# interpreter ("bad interpreter: Permission denied"), because whatever
# is actually enforced at the syscall level doesn't match what `ls`
# reports. COPY + RUN chmod happen inside Docker's own build process,
# writing straight into the image's filesystem layer -- no host
# translation layer is involved, so this class of bug cannot occur here.
#
# Trade-off: changes to db/ now require `docker compose build`, not just
# a file edit + restart. That's a reasonable price for "this definitely
# works regardless of host OS/Docker Desktop version," and arguably
# closer to how you'd want this to work in production anyway (an
# immutable image, not a live host mount).

COPY db/docker-init/00-bootstrap.sh /docker-entrypoint-initdb.d/00-bootstrap.sh
COPY db/bootstrap.sh /app-db/bootstrap.sh
COPY db/roles.sql /app-db/roles.sql
COPY db/migrations /app-db/migrations

RUN chmod +x /docker-entrypoint-initdb.d/00-bootstrap.sh /app-db/bootstrap.sh
