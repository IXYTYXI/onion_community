const allowedItemKeys = new Set(["name", "uses", "state", "managed"]);
const states = new Set(["missing", "configured", "unavailable"]);

export function secretInputError(value) {
  if (typeof value !== "string" || !value) return "请输入密钥。";
  if (/[\r\n\0]/.test(value)) return "密钥不能包含换行或空字符。";
  if (new TextEncoder().encode(value).length > 16384)
    return "密钥不能超过 16 KiB。";
  return "";
}

export function checkedRequirements(job, data) {
  const items = data?.items;
  if (
    data?.jobId !== job.id ||
    data?.repository !== job.repository ||
    data?.subdomain !== job.subdomain ||
    typeof data?.canGenerate !== "boolean" ||
    !Array.isArray(items) ||
    new Set(items.map((item) => item.name)).size !== items.length ||
    items.some(
      (item) =>
        !item ||
        Object.keys(item).some((key) => !allowedItemKeys.has(key)) ||
        !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(item.name) ||
        !states.has(item.state) ||
        typeof item.managed !== "boolean" ||
        !Array.isArray(item.uses) ||
        item.uses.some(
          (use) =>
            typeof use?.service !== "string" ||
            typeof use?.environmentVariable !== "string",
        )
    )
  )
    throw new Error("配置状态与当前部署不一致，请重新读取。");
  return data;
}

export function continuationRequest(job) {
  return {
    body: {
      repository: job.repository,
      name: job.subdomain,
      ...(job.appId ? { app_id: job.appId } : {}),
    },
    key: `configure-${job.id}`,
  };
}
