<script setup>
defineProps({ status: String });
const labels = {
  queued: "等待部署",
  running: "正在部署",
  succeeded: "部署成功",
  failed: "部署失败",
  recovery_required: "等待恢复处理",
  cancelled: "已取消",
};
</script>
<template>
  <span class="deployment-status" :data-status="status"
    ><i aria-hidden="true"></i>{{ labels[status] || status }}</span
  >
</template>
<style scoped>
.deployment-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #edf3fb;
  color: #436998;
  white-space: nowrap;
}
i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
[data-status="succeeded"] {
  background: #e3f5ed;
  color: #1c755d;
}
[data-status="failed"],
[data-status="recovery_required"] {
  background: #fff0ec;
  color: #a84839;
}
[data-status="running"] {
  background: #e6f0ff;
  color: #215fd0;
}
</style>
