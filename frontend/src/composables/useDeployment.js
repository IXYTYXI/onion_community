import { auth } from "../services/auth.js";
import { checkedPreflight, secretInputError } from "../services/deployment-secrets.js";
import {
  computed,
  reactive,
  ref,
  watch,
  onMounted,
  onBeforeUnmount,
  getCurrentInstance,
} from "vue";

export function projectNameError(value) {
  if (!value) return "请填写项目名称。";
  if (
    value !== value.trim() ||
    !/^[a-z0-9](?:[a-z0-9-]{0,5}[a-z0-9])?$/.test(value)
  )
    return "请输入 1–7 位小写字母、数字或中划线，首尾须为字母或数字。";
  return "";
}

export function repositoryError(value) {
  if (!value.trim()) return "请填写 GitHub / GitLab 仓库地址。";
  try {
    const url = new URL(value.trim());
    const parts = url.pathname.replace(/\/$/, "").split("/").filter(Boolean);
    if (
      url.protocol !== "https:" ||
      !url.hostname.includes(".") ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      /\s/.test(value.trim()) ||
      parts.length < 2 ||
      parts.some((p) => !/^[\w.-]+$/.test(p)) ||
      parts.includes("-") ||
      ["tree", "blob", "issues", "pull", "merge_requests"].some((p) =>
        parts.includes(p),
      )
    )
      throw new Error();
    // GitLab may be self-hosted and may use nested groups. Verify syntax only here.
    if (url.hostname === "github.com" && parts.length !== 2) throw new Error();
    return "";
  } catch {
    return "请输入完整的 HTTPS 仓库地址，例如 https://github.com/team/project.git。";
  }
}

export function useDeployment() {
  const step = ref(0);
  const busy = ref(false);
  const job = ref(null);
  const history = ref([]);
  const preflight = ref(null);
  const secretValues = reactive(Object.create(null));
  const options = ref({
    executionEnabled: false,
    baseDomain: "awesome.guanghexinzhi.cn",
  });
  let timer,
    controller,
    preflightController,
    preflightVersion = 0,
    inspectedInput = "",
    inspectedApplication = "",
    pollVersion = 0,
    requestKey = "",
    requestPayload = "",
    disposed = false;
  function stopPolling() {
    pollVersion++;
    clearTimeout(timer);
    controller?.abort();
  }
  function rememberJob(item) {
    const index = history.value.findIndex((entry) => entry.id === item.id);
    if (index === -1) history.value = [item, ...history.value];
    else history.value = history.value.map((entry, position) =>
      position === index ? item : entry,
    );
  }
  async function poll(id, version = pollVersion) {
    if (disposed || version !== pollVersion) return;
    controller = new AbortController();
    const signal = controller.signal;
    try {
      const result = await auth.request(
        `/api/v1/deployment/jobs/${encodeURIComponent(id)}`,
        { signal },
      );
      if (disposed || version !== pollVersion) return;
      job.value = result;
      rememberJob(result);
      if (!result.terminal) timer = setTimeout(() => poll(id, version), 5000);
      else {
        const rows = await auth.request("/api/v1/deployment/jobs", { signal });
        if (!disposed && version === pollVersion) history.value = rows;
      }
    } catch (error) {
      if (disposed || version !== pollVersion || error.name === "AbortError")
        return;
      notice.value = error.message;
      if (![401, 403, 404].includes(error.status))
        timer = setTimeout(() => poll(id, version), 10000);
    }
  }
  function viewJob(item) {
    stopPolling();
    job.value = item;
    rememberJob(item);
    return poll(item.id);
  }
  if (getCurrentInstance()) {
    onMounted(async () => {
      try {
        options.value = await auth.request("/api/v1/deployment/options");
        history.value = await auth.request("/api/v1/deployment/jobs");
        const pending = history.value.find((item) => !item.terminal);
        if (pending) viewJob(pending);
      } catch (error) {
        notice.value = error.message;
      }
    });
    onBeforeUnmount(() => {
      disposed = true;
      stopPolling();
      preflightController?.abort();
      for (const name of Object.keys(secretValues)) delete secretValues[name];
    });
  }
  const form = reactive({ application: "create", repository: "", name: "" });
  const applications = computed(() => [
    ...new Map(
      history.value
        .filter((item) => item.appId)
        .slice()
        .reverse()
        .map((item) => [item.appId, item]),
    ).values(),
  ]);
  watch(
    () => form.application,
    (id) => {
      const app = applications.value.find((item) => item.appId === id);
      if (app) {
        form.repository = app.repository;
        form.name = app.subdomain;
      }
    },
  );
  const nameFeedback = ref("");
  const nameTaken = ref(false);
  let nameTimer,
    nameController,
    nameVersion = 0;
  if (getCurrentInstance()) {
    watch(
      () => [form.name, form.application],
      () => {
        clearTimeout(nameTimer);
        nameController?.abort();
        const version = ++nameVersion;
        nameTaken.value = false;
        nameFeedback.value = "";
        if (projectNameError(form.name)) return;
        nameFeedback.value = "正在检查名称…";
        nameTimer = setTimeout(async () => {
          nameController = new AbortController();
          try {
            const query = new URLSearchParams({ name: form.name });
            if (form.application !== "create")
              query.set("app_id", form.application);
            const result = await auth.request(
              `/api/v1/deployment/name-availability?${query}`,
              { signal: nameController.signal },
            );
            if (disposed || version !== nameVersion) return;
            nameTaken.value = !result.available;
            nameFeedback.value = result.available
              ? "名称可用，提交时将再次确认。"
              : "项目名称已存在，请更换名称或选择已有应用。";
          } catch (error) {
            if (
              !disposed &&
              version === nameVersion &&
              error.name !== "AbortError"
            )
              nameFeedback.value = "名称检查暂不可用，提交时将再次确认。";
          }
        }, 350);
      },
    );
    onBeforeUnmount(() => {
      clearTimeout(nameTimer);
      nameController?.abort();
    });
  }
  const touched = reactive([false, false, false, false]);
  const notice = ref("");
  const errors = computed(() => [
    form.application === "create" ||
    applications.value.some((item) => item.appId === form.application)
      ? ""
      : "请选择有效应用。",
    repositoryError(form.repository),
    !preflight.value ? "请先检查仓库配置。" :
      preflight.value.canPreconfigure
        ? (preflight.value.items.find((item) => item.state === "unavailable")
            ? "部分密钥需要管理员恢复。" :
          preflight.value.items.filter((item) => item.state === "missing" && !item.managed)
            .map((item) => [item.name, secretInputError(secretValues[item.name] || "")])
            .filter(([, error]) => error)
            .map(([name, error]) => `${name}：${error}`)[0] || "")
        : "",
    projectNameError(form.name) ||
      (preflight.value && form.name !== preflight.value.subdomain
        ? "名称须与 awesome.yaml 的 app.subdomain 一致。" : "") ||
      (nameTaken.value ? "项目名称已存在，请更换名称或选择已有应用。" : ""),
  ]);
  async function next() {
    if (step.value >= 4 || busy.value) return;
    touched[step.value] = true;
    if (errors.value[step.value]) return;
    if (step.value === 1) {
      const version = ++preflightVersion;
      preflightController?.abort();
      preflightController = new AbortController();
      const input = form.repository.trim();
      const application = form.application;
      busy.value = true;
      notice.value = "正在读取仓库配置…";
      try {
        const result = checkedPreflight(await auth.request("/api/v1/deployment/preflight", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repository: input,
            ...(application === "create" ? {} : { app_id: application }) }),
          signal: preflightController.signal,
        }));
        if (disposed || version !== preflightVersion || input !== form.repository.trim()
            || application !== form.application) return;
        preflight.value = result;
        inspectedInput = input;
        inspectedApplication = application;
        for (const name of Object.keys(secretValues)) delete secretValues[name];
        form.name = result.subdomain;
        const needsInput = result.items.some((item) => item.state === "unavailable" ||
          (item.state === "missing" && !item.managed));
        step.value = needsInput ? 2 : 3;
        notice.value = result.items.length ? "" : "仓库无需配置密钥，已跳过该步骤。";
      } catch (error) {
        if (!disposed && version === preflightVersion && error.name !== "AbortError")
          notice.value = error.message || "无法读取仓库配置，请重试。";
      } finally {
        if (!disposed && version === preflightVersion) busy.value = false;
      }
      return;
    }
    step.value++;
    notice.value = "";
  }
  function back(index = step.value - 1) {
    if (index === 2 && preflight.value && !preflight.value.items.some((item) =>
      item.state === "unavailable" || (item.state === "missing" && !item.managed))) index = 1;
    if (index >= 0 && index < step.value) {
      if (busy.value && step.value === 1) {
        preflightVersion++;
        preflightController?.abort();
        busy.value = false;
      }
      step.value = index;
      notice.value = "";
    }
  }
  async function submit() {
    if (busy.value) return;
    const pending = history.value.find(
      (item) =>
        !item.terminal &&
        (item.appId === form.application || item.subdomain === form.name),
    );
    if (pending || (job.value && !job.value.terminal)) {
      notice.value = "该应用已有进行中的部署，请等待任务完成。";
      return;
    }
    if (step.value !== 4) return;
    touched.fill(true);
    const invalid = errors.value.findIndex(Boolean);
    if (invalid !== -1) {
      step.value = invalid;
      return;
    }
    if (!options.value.executionEnabled) {
      notice.value = "部署执行环境待配置，暂未发起部署。";
      return;
    }
    if (!preflight.value || inspectedInput !== form.repository.trim() ||
        inspectedApplication !== form.application) {
      step.value = 1;
      notice.value = "仓库或应用已变化，请重新检查配置。";
      return;
    }
    const values = Object.fromEntries(preflight.value.items
      .filter((item) => item.state === "missing" && !item.managed)
      .map((item) => [item.name, secretValues[item.name]]));
    const payload = JSON.stringify({
      repository: form.repository.trim(),
      name: form.name,
      commit: preflight.value.commit,
      values,
      ...(form.application === "create" ? {} : { app_id: form.application }),
    });
    if (
      payload !== requestPayload ||
      (job.value?.terminal && job.value.subdomain === form.name)
    ) {
      requestKey = crypto.randomUUID();
      requestPayload = payload;
    }
    busy.value = true;
    notice.value = "";
    try {
      job.value = await auth.request("/api/v1/deployment/jobs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": requestKey,
        },
        body: payload,
      });
      if (!disposed) viewJob(job.value);
      for (const name of Object.keys(secretValues)) delete secretValues[name];
      requestPayload = "";
    } catch (error) {
      notice.value = error.message;
    } finally {
      busy.value = false;
    }
  }
  return {
    nameFeedback,
    step,
    form,
    touched,
    errors,
    notice,
    next,
    back,
    submit,
    busy,
    job,
    history,
    preflight,
    secretValues,
    options,
    viewJob,
    applications,
  };
}
