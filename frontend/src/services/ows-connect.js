export const installUrl = 'https://ai.lab.yc345.tv/files/d/ows-install.md';

export const installPrompt = '请阅读 [https://ai.lab.yc345.tv/files/d/ows-install.md](https://ai.lab.yc345.tv/files/d/ows-install.md)，按说明为当前 Agent 安装 OWS CLI、ows-knowledge 和 ows-upload。使用推荐版本并校验文件，将 CLI 安装到持久目录，确保后续会话可调用。安装后检查命令与 Skill，最后引导我本人完成飞书登录和设备确认。';

export function normalizeCopyStats(data) {
  if (!data || typeof data !== 'object') return null;
  const uniqueUsers = Number(data.unique_users);
  const totalCopies = Number(data.total_copies);
  const myCopies = Number(data.my_copies ?? 0);
  if (!Number.isInteger(uniqueUsers) || uniqueUsers < 0 || !Number.isInteger(totalCopies) || totalCopies < 0) {
    return null;
  }
  return {
    unique_users: uniqueUsers,
    total_copies: totalCopies,
    my_copies: Number.isInteger(myCopies) && myCopies >= 0 ? myCopies : 0,
  };
}

export async function fetchOwsCopyStats(request) {
  const data = await request('/api/v1/ows-release/copy-stats');
  return normalizeCopyStats(data);
}

export async function recordOwsCopy(request, cliVersion) {
  const payload = cliVersion ? { cli_version: String(cliVersion) } : {};
  const data = await request('/api/v1/ows-release/copy-stats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return normalizeCopyStats(data);
}
