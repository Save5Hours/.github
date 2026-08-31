FROM n8nio/n8n:1.123.75

# Pin 1.x so Code nodes run inside this image.
# n8n 2.x (docker tag latest) expects task runners; do not use it for this workflow
# unless you also deploy n8nio/runners.
# Railway: N8N_PORT=${{PORT}}, volume /home/node/.n8n, set N8N_ENCRYPTION_KEY
# before the first boot (see scripts/deploy-railway.sh).

USER root
COPY n8n/meeting-notes-to-tasks.json /opt/save5hours/meeting-notes-to-tasks.json
COPY scripts/n8n-boot.sh /opt/save5hours/n8n-boot.sh
RUN chmod +x /opt/save5hours/n8n-boot.sh \
  && chown -R node:node /opt/save5hours
USER node
ENTRYPOINT ["tini", "--", "/opt/save5hours/n8n-boot.sh"]
