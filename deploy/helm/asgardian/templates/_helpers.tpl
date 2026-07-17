{{- define "asgardian.labels" -}}
app.kubernetes.io/name: asgardian
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "asgardian.workerAffinity" -}}
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: node-role.kubernetes.io/control-plane
              operator: DoesNotExist
            - key: asgardian.io/runtime
              operator: In
              values: ["true"]
{{- end }}

{{- define "asgardian.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{- define "asgardian.env" -}}
- name: ASGARDIAN_DATABASE_URL
  valueFrom: { secretKeyRef: { name: asgardian-runtime, key: database-url } }
- name: ASGARDIAN_REDIS_URL
  value: {{ .Values.config.redisUrl | quote }}
- name: ASGARDIAN_S3_ACCESS_KEY
  valueFrom: { secretKeyRef: { name: asgardian-runtime, key: s3-access-key } }
- name: ASGARDIAN_S3_SECRET_KEY
  valueFrom: { secretKeyRef: { name: asgardian-runtime, key: s3-secret-key } }
- name: ASGARDIAN_COMFY_URL
  value: {{ .Values.config.comfyUrl | quote }}
- name: ASGARDIAN_ENGINE_ROUTING_MODE
  value: {{ .Values.config.engineRoutingMode | quote }}
- name: ASGARDIAN_COMFY_IMAGE_URL
  value: {{ .Values.config.comfyImageUrl | quote }}
- name: ASGARDIAN_COMFY_VIDEO_URL
  value: {{ .Values.config.comfyVideoUrl | quote }}
- name: ASGARDIAN_S3_ENDPOINT
  value: {{ .Values.config.s3Endpoint | quote }}
- name: ASGARDIAN_S3_BUCKET
  value: {{ .Values.config.s3Bucket | quote }}
- name: ASGARDIAN_S3_TLS_VERIFY
  value: {{ .Values.config.s3TlsVerify | quote }}
- name: ASGARDIAN_ALLOWED_HOSTS
  value: {{ .Values.config.allowedHosts | quote }}
- name: ASGARDIAN_ALLOWED_ORIGINS
  value: {{ .Values.config.allowedOrigins | quote }}
- name: ASGARDIAN_WORKFLOW_DIR
  value: /app/workflows
- name: ASGARDIAN_WALL_TTL_SECONDS
  value: {{ .Values.config.wallTtlSeconds | quote }}
- name: ASGARDIAN_CLEANUP_BATCH_SIZE
  value: {{ .Values.cleanup.batchSize | quote }}
{{- end }}
