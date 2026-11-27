<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import PageBreadcrumb from "../components/PageBreadcrumb.vue";
import DeploymentActivity from "../components/deployment/DeploymentActivity.vue";
import DeploymentPreflightSecrets from "../components/deployment/DeploymentPreflightSecrets.vue";
import PageHeading from "../components/PageHeading.vue";
import { useDeployment } from "../composables/useDeployment.js";
const {
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
  options,
  viewJob,
  applications,
  preflight,
  secretValues,
  scopeMode,
  hasOtherUsersRecords,
} = useDeployment();
const steps = ["选择应用", "连接仓库", "配置运行密钥", "项目名称", "确认部署"];
const stepTitle = ref(null);
const wizard = ref(null);
const secretFields = ref(null);
const pickerWrap = ref(null);
const pickerSearchInput = ref(null);
const dropdownOpen = ref(false);
const showDraftApps = ref(false);
const appSearch = ref("");

const selectedApp = computed(() =>
  form.application === "create"
    ? null
    : applications.value.find((item) => item.appId === form.application) || null,
);

const isUnpublishedDraft = (app) =>
  app.appOnline === false && app.everSucceeded === false && app.status === "failed";

const filteredApps = computed(() => {
  const q = appSearch.value.trim().toLowerCase();
  if (!q) return applications.value;
  return applications.value.filter(
    (app) =>
      (app.subdomain || "").toLowerCase().includes(q) ||
      (app.repository || "").toLowerCase().includes(q) ||
      (app.ownerName || "").toLowerCase().includes(q),
  );
});

const primaryApps = computed(() =>
  filteredApps.value.filter((app) => !isUnpublishedDraft(app)),
);

const draftApps = computed(() =>
  filteredApps.value.filter((app) => isUnpublishedDraft(app)),
);

const shortRepository = computed(() => {
  const raw = form.repository.trim();
  if (!raw || errors.value[1]) return "";
  try {
    const u = new URL(raw);
    return u.pathname.replace(/^\/+|\.git$|\/+$/g, "");
  } catch {
    return raw;
  }
});

function shortRepoText(url) {
  try {
    return new URL(url).pathname.replace(/^\/+|\.git$|\/+$/g, "");
  } catch {
    return url || "";
  }
}

function toggleDropdown() {
  dropdownOpen.value = !dropdownOpen.value;
  if (dropdownOpen.value) {
    appSearch.value = "";
    if (selectedApp.value && isUnpublishedDraft(selectedApp.value)) {
      showDraftApps.value = true;
    }
    nextTick(() => pickerSearchInput.value?.focus());
  }
}

function chooseApplication(value) {
  form.application = value;
  if (value === "create") {
    form.repository = "";
    form.name = "";
  }
  dropdownOpen.value = false;
}

function onDocumentPointerDown(event) {
  if (dropdownOpen.value && pickerWrap.value && !pickerWrap.value.contains(event.target)) {
    dropdownOpen.value = false;
  }
}

function onPickerKeydown(event) {
  if (event.key === "Escape" && dropdownOpen.value) {
    event.stopPropagation();
    dropdownOpen.value = false;
  }
}

watch(step, () => {
  dropdownOpen.value = false;
});

function revealStep() {
  stepTitle.value?.focus({ preventScroll: true });
  wizard.value?.scrollIntoView({
    block: "start",
    behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
  });
}
const progress = computed(() => Math.round((step.value / 4) * 100));
const skippedSecrets = computed(() => !!preflight.value && !preflight.value.items.some((item) =>
  item.state === "unavailable" || (item.state === "missing" && !item.managed)));
const domainName = computed(() => form.name || "项目名称");
async function continueStep() {
  if (step.value === 4) return submit();
  const prior = step.value;
  await next();
  if (prior === 2 && step.value === 2 && errors.value[2]) {
    await nextTick();
    secretFields.value?.focusFirstError();
  }
}
function hasPendingSecretInput() {
  return Object.values(secretValues).some((value) => value);
}
function beforeUnload(event) {
  if (!hasPendingSecretInput()) return;
  event.preventDefault();
  event.returnValue = "";
}
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  document.addEventListener("pointerdown", onDocumentPointerDown);
});
onUnmounted(() => {
  window.removeEventListener("beforeunload", beforeUnload);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
});
onBeforeRouteLeave(() => !hasPendingSecretInput() || window.confirm("已填写的密钥尚未提交，离开后需要重新填写。确定离开吗？"));
</script>

<template>
  <main class="portal-page deployment-page wrap" id="main-content">
    <PageBreadcrumb current="一键部署" />
    <header class="deploy-heading">
      <div>
        <PageHeading>一键部署<span class="deployment-dot">.</span></PageHeading>
        <p>从代码仓库，到你的应用。</p>
      </div>
      <a class="deploy-skill-download" href="/assets/awesome-deploy-protocol-20261117-r4.zip" download="awesome-deploy-protocol-20261117-r4.zip" title="下载完整 Skill 安装包（r4）">
        <Icon name="file-down" />下载部署配置 Skill
      </a>
    </header>

    <section class="resource-card" aria-labelledby="resource-title">
      <div class="resource-heading">
        <span class="resource-icon"><Icon name="triangle-alert" /></span>
        <div>
          <span class="resource-eyebrow">部署前请确认</span>
          <h2 id="resource-title">每应用资源上限</h2>
        </div>
        <span class="resource-badge">多个服务按应用合计</span>
      </div>
      <div class="resource-values">
        <div>
          <Icon name="hard-drive" /><span>持久数据</span
          ><strong>50 <small>MiB</small></strong>
        </div>
        <div>
          <Icon name="memory-stick" /><span>运行内存</span
          ><strong>500 <small>MiB</small></strong>
        </div>
        <div class="resource-pool">
          <Icon name="layers" /><span>平台共享存储池</span
          ><strong>64 <small>GiB</small></strong>
        </div>
      </div>
      <p class="resource-warning">
        <Icon name="info" /><span
          >内存按需使用，不固定预占；<strong
            >写满存储会阻止继续写入，内存超限可能终止服务。</strong
          ></span
        >
      </p>
    </section>

    <section ref="wizard" class="deploy-wizard" aria-label="部署配置向导">
      <div class="wizard-progress-heading">
        <span>部署配置</span
        ><span
          >步骤 <b>{{ step + 1 }}</b> / 5</span
        >
      </div>
      <nav class="deploy-steps" aria-label="部署步骤">
        <div
          class="step-track"
          role="progressbar"
          aria-label="配置进度"
          :aria-valuenow="progress"
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <span :style="{ width: progress + '%' }"></span>
        </div>
        <ol>
          <li
            v-for="(label, index) in steps"
              :key="label"
              :class="{ current: step === index, complete: index < step, skipped: index === 2 && skippedSecrets }"
          >
            <button
              type="button"
              :disabled="index > step || (index === 2 && skippedSecrets)"
              :aria-current="index === step ? 'step' : undefined"
              :aria-label="
                (index < step ? '返回' : '') +
                '第' +
                (index + 1) +
                '步：' +
                (index === 2 && skippedSecrets ? '运行密钥无需配置，已跳过' : label)
              "
              @click="back(index)"
            >
              <span class="step-node"
                ><Icon v-if="index < step" name="check" /><span v-else>{{
                  String(index + 1).padStart(2, "0")
                }}</span></span
              >
              <span class="step-label">{{ index === 2 && skippedSecrets ? "无需配置密钥" : label }}</span>
            </button>
          </li>
        </ol>
      </nav>

      <div class="wizard-body">
        <div class="deploy-form-stack">
        <form class="deploy-form" novalidate @submit.prevent="continueStep">
          <Transition
            name="deploy-step"
            mode="out-in"
            @after-enter="revealStep"
          >
            <div :key="step" class="step-content">
              <div class="step-kicker">
                <span>{{ String(step + 1).padStart(2, "0") }}</span
                ><span v-if="step < 4" class="required-chip">{{ step === 2 ? "按需填写" : "必填" }}</span
                ><span v-else class="review-chip">最后一步</span>
              </div>
              <h2 ref="stepTitle" tabindex="-1">{{ steps[step] }}</h2>
              <template v-if="step === 0">
                <p class="step-description">选择本次部署要创建新应用，或更新已有的线上应用。</p>
                <div class="field-label-row">
                  <label id="deploy-application-label" for="deploy-application">
                    应用 <span class="required-star">*</span>
                  </label>
                  <div v-if="hasOtherUsersRecords" class="scope-pills" role="group" aria-label="应用归属范围">
                    <button
                      type="button"
                      :class="{ active: scopeMode === 'mine' }"
                      @click="scopeMode = 'mine'"
                    >
                      我的应用
                    </button>
                    <button
                      type="button"
                      :class="{ active: scopeMode === 'all' }"
                      @click="scopeMode = 'all'"
                    >
                      全平台
                    </button>
                  </div>
                </div>

                <div ref="pickerWrap" class="deploy-app-picker" @keydown="onPickerKeydown">
                  <button
                    id="deploy-application"
                    type="button"
                    class="app-picker-trigger"
                    :class="{ open: dropdownOpen }"
                    role="combobox"
                    aria-labelledby="deploy-application-label"
                    aria-haspopup="listbox"
                    :aria-expanded="dropdownOpen"
                    :aria-invalid="!!errors[0]"
                    aria-describedby="application-error"
                    @click="toggleDropdown"
                  >
                    <span class="trigger-leading" :class="{ 'is-existing': !!selectedApp }">
                      <Icon :name="selectedApp ? 'rocket' : 'plus'" />
                    </span>
                    <span class="trigger-copy">
                      <strong>{{ selectedApp ? `更新 ${selectedApp.subdomain}` : "创建新应用" }}</strong>
                      <small v-if="selectedApp">
                        {{ selectedApp.subdomain }}.{{ options.baseDomain }}
                      </small>
                      <small v-else>分配独立子域名与运行容器</small>
                    </span>
                    <span v-if="selectedApp?.appOnline" class="app-pill app-pill--online">运行中</span>
                    <span v-else-if="selectedApp" class="app-pill app-pill--draft">可更新</span>
                    <TripleArrow compact :direction="dropdownOpen ? 'up' : 'down'" class="trigger-chevron" />
                  </button>

                  <div v-if="dropdownOpen" class="app-picker-popover" role="listbox" aria-labelledby="deploy-application-label">
                    <div v-if="applications.length >= 5" class="picker-search-box">
                      <Icon name="search" />
                      <input
                        ref="pickerSearchInput"
                        v-model="appSearch"
                        type="search"
                        placeholder="搜索应用名称或仓库…"
                        aria-label="搜索已有应用"
                      />
                    </div>

                    <div class="picker-options-scroll">
                      <button
                        type="button"
                        role="option"
                        class="picker-option picker-option--create"
                        :class="{ selected: form.application === 'create' }"
                        :aria-selected="form.application === 'create'"
                        @click="chooseApplication('create')"
                      >
                        <span class="option-badge option-badge--create"><Icon name="plus" /></span>
                        <span class="option-body">
                          <strong>创建新应用</strong>
                          <small>为新项目分配独立访问地址与运行环境</small>
                        </span>
                        <Icon v-if="form.application === 'create'" name="check" class="option-check" />
                      </button>

                      <template v-if="primaryApps.length">
                        <div class="picker-group-label">已有应用 ({{ primaryApps.length }})</div>
                        <button
                          v-for="app in primaryApps"
                          :key="app.appId"
                          type="button"
                          role="option"
                          class="picker-option"
                          :class="{ selected: form.application === app.appId }"
                          :aria-selected="form.application === app.appId"
                          @click="chooseApplication(app.appId)"
                        >
                          <span class="option-badge" :class="{ online: app.appOnline }">
                            <Icon name="rocket" />
                          </span>
                          <span class="option-body">
                            <span class="option-title-row">
                              <strong>更新 {{ app.subdomain }}</strong>
                              <span v-if="app.appOnline" class="app-pill app-pill--online">运行中</span>
                              <span v-if="scopeMode === 'all' && app.ownerName && app.mine === false" class="app-pill app-pill--owner">
                                {{ app.ownerName }}
                              </span>
                            </span>
                            <small>{{ app.subdomain }}.{{ options.baseDomain }} · {{ shortRepoText(app.repository) }}</small>
                          </span>
                          <Icon v-if="form.application === app.appId" name="check" class="option-check" />
                        </button>
                      </template>

                      <template v-if="draftApps.length">
                        <button
                          v-if="!appSearch"
                          type="button"
                          class="picker-draft-toggle"
                          :aria-expanded="showDraftApps"
                          @click.stop="showDraftApps = !showDraftApps"
                        >
                          <span>{{ showDraftApps ? "收起" : "展开" }} {{ draftApps.length }} 个未完成首次上线的草稿</span>
                          <Icon name="chevron-right" :class="{ rotated: showDraftApps }" />
                        </button>
                        <div v-if="showDraftApps || appSearch" class="picker-draft-list">
                          <button
                            v-for="app in draftApps"
                            :key="app.appId"
                            type="button"
                            role="option"
                            class="picker-option picker-option--draft"
                            :class="{ selected: form.application === app.appId }"
                            :aria-selected="form.application === app.appId"
                            @click="chooseApplication(app.appId)"
                          >
                            <span class="option-badge option-badge--draft"><Icon name="blocks" /></span>
                            <span class="option-body">
                              <span class="option-title-row">
                                <strong>继续部署 {{ app.subdomain }}</strong>
                                <span class="app-pill app-pill--draft">未上线草稿</span>
                                <span v-if="scopeMode === 'all' && app.ownerName && app.mine === false" class="app-pill app-pill--owner">
                                  {{ app.ownerName }}
                                </span>
                              </span>
                              <small>{{ shortRepoText(app.repository) }}</small>
                            </span>
                            <Icon v-if="form.application === app.appId" name="check" class="option-check" />
                          </button>
                        </div>
                      </template>

                      <p v-if="appSearch && !primaryApps.length && !draftApps.length" class="picker-no-match">
                        未找到匹配「{{ appSearch }}」的应用
                      </p>
                    </div>
                  </div>
                </div>

                <p
                  v-if="errors[0]"
                  id="application-error"
                  class="field-error"
                  role="alert"
                >
                  {{ errors[0] }}
                </p>
                <div v-if="selectedApp" class="application-note application-note--existing">
                  <span class="application-icon"><Icon name="rocket" /></span>
                  <div class="application-note-copy">
                    <strong>更新 {{ selectedApp.subdomain }}.{{ options.baseDomain }}</strong>
                    <p>将从绑定仓库 <code>{{ shortRepoText(selectedApp.repository) }}</code> 拉取最新 <code>main</code> 分支平滑发布，已保存密钥自动沿用。</p>
                  </div>
                  <a
                    v-if="selectedApp.url"
                    class="application-live-btn"
                    :href="selectedApp.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    访问线上 <Icon name="arrow-up-right" />
                  </a>
                </div>
                <div v-else class="application-note">
                  <span class="application-icon"><Icon name="blocks" /></span>
                  <div>
                    <strong>新的开始</strong>
                    <p>为你的项目创建独立应用与专属访问地址。</p>
                  </div>
                </div>
              </template>
              <template v-else-if="step === 1">
                <p class="step-description">连接需要部署的代码仓库。</p>
                <label for="deploy-repository"
                  >GitHub / GitLab 仓库地址
                  <span class="required-star">*</span></label
                >
                <div class="deploy-input-wrap">
                  <Icon name="git-branch" /><input
                    id="deploy-repository"
                    v-model="form.repository"
                    type="url"
                    required
                    autocomplete="off"
                    spellcheck="false"
                    placeholder="https://github.com/team/project.git"
                    :aria-invalid="touched[1] && !!errors[1]"
                    aria-describedby="repository-help repository-error"
                    @blur="touched[1] = true"
                  />
                </div>
                <p id="repository-help" class="field-help">
                  默认部署 <code>main</code> 分支，无需填写版本。支持自建 GitLab
                  仓库。
                </p>
                <p id="repository-error" class="field-error" role="alert">
                  {{ touched[1] ? errors[1] : "" }}
                </p>
              </template>
              <template v-else-if="step === 2">
                <p class="step-description">根据仓库配置填写应用运行所需的密钥。已配置的值不会显示或覆盖。</p>
                <DeploymentPreflightSecrets
                  v-if="preflight"
                  ref="secretFields"
                  :items="preflight.items"
                  :can-preconfigure="preflight.canPreconfigure"
                  :values="secretValues"
                  :attempted="touched[2]"
                  :busy="busy"
                  @input="(name, value) => secretValues[name] = value"
                />
                <p v-if="touched[2] && errors[2]" class="field-error" role="alert">{{ errors[2] }}</p>
              </template>
              <template v-else-if="step === 3">
                <p class="step-description">给应用一个简短、好记的访问名称。</p>
                <label for="deploy-name"
                  >项目名称 <span class="required-star">*</span></label
                >
                <div class="deploy-input-wrap name-input">
                  <input
                    id="deploy-name"
                    v-model="form.name"
                    required
                    autocomplete="off"
                    autocapitalize="none"
                    spellcheck="false"
                    placeholder="例如 demo"
                    :aria-invalid="(touched[3] || !!form.name) && !!errors[3]"
                    aria-describedby="name-help name-error domain-preview"
                    @blur="touched[3] = true"
                  /><span :class="{ invalid: form.name.length > 7 }"
                    >{{ form.name.length }} / 7</span
                  >
                </div>
                <p id="name-help" class="field-help">
                  1–7
                  位小写字母、数字或中划线（-），首尾须为字母或数字；不能包含中文、空格或大写字母。名称用于访问域名，须与
                  <code>awesome.yaml</code> 的 <code>subdomain</code> 一致。
                </p>
                <p id="name-error" class="field-error" role="alert">
                  {{ touched[3] || form.name ? errors[3] : "" }}
                </p>
                <p
                  v-if="nameFeedback && !errors[3]"
                  class="field-help"
                  role="status"
                >
                  {{ nameFeedback }}
                </p>
                <div
                  id="domain-preview"
                  class="domain-preview"
                  aria-live="polite"
                >
                  <Icon name="globe" />
                  <div>
                    <span>访问地址</span>
                    <p>
                      <strong :class="{ invalid: form.name && errors[3] }">{{
                        domainName
                      }}</strong
                      ><span>.{{ options.baseDomain }}</span>
                    </p>
                  </div>
                </div>
              </template>
              <template v-else>
                <p class="step-description">检查配置信息，准备部署。</p>
                <dl class="deployment-review">
                  <div>
                    <dt>应用</dt>
                    <dd>
                      {{
                        form.application === "create"
                          ? "创建新应用"
                          : "更新已有应用"
                      }}
                    </dd>
                  </div>
                  <div>
                    <dt>代码仓库</dt>
                    <dd>{{ form.repository.trim() }}</dd>
                  </div>
                  <div>
                    <dt>部署分支</dt>
                    <dd><code>main · {{ preflight?.commit?.slice(0, 8) }}</code></dd>
                  </div>
                  <div>
                    <dt>运行密钥</dt>
                    <dd>{{ preflight?.items.length ? `${preflight.items.length} 项声明，已检查` : "无需配置" }}</dd>
                  </div>
                  <div>
                    <dt>项目名称</dt>
                    <dd>{{ form.name }}</dd>
                  </div>
                </dl>
                <div class="domain-preview">
                  <Icon name="globe" />
                  <div>
                    <span>访问地址</span>
                    <p>
                      <strong>{{ domainName }}</strong
                      ><span>.{{ options.baseDomain }}</span>
                    </p>
                  </div>
                </div>
                <p class="preview-mode">
                  <Icon name="info" />{{ options.executionEnabled ? "提交后将自动拉取 main 分支，校验配置并开始部署。" : "部署环境暂不可用，请稍后再试。" }}
                </p>
              </template>
            </div>
          </Transition>
          <div class="wizard-actions">
            <button
              v-if="step > 0"
              type="button"
              class="previous-step"
              @click="back()"
            >
              <TripleArrow compact direction="left" />上一步</button
            ><span v-else class="step-guidance">按步骤完成配置</span
            ><button
              type="submit"
              class="next-step"
              :disabled="
                busy ||
                (step === 4 &&
                  (!options.executionEnabled || (job && !job.terminal)))
              "
            >
              <Icon v-if="step === 4" name="rocket" />{{
                busy ? (step === 1 ? "正在检查仓库…" : "正在提交…") : step === 4 ? "开始部署" : "下一步"
              }}<TripleArrow v-if="step < 4" compact />
            </button>
          </div>
          <p v-if="!options.executionEnabled" class="deployment-notice">
            部署执行环境待配置，暂未开放提交。
          </p>
        </form>
        <DeploymentActivity
          :job="job"
          :history="history"
          :scope-mode="scopeMode"
          :has-other-users-records="hasOtherUsersRecords"
          @select="viewJob"
          @continued="viewJob"
          @update:scope-mode="scopeMode = $event"
        />
        <p v-if="notice" class="deployment-notice" role="status">
          <Icon name="info" />{{ notice }}
        </p>
        </div>

        <aside class="deploy-blueprint" aria-label="应用配置概览">
          <div class="blueprint-top">
            <span class="blueprint-dot"></span>你的应用
          </div>
          <div class="blueprint-art" aria-hidden="true">
            <span class="blueprint-orbit"></span
            ><span class="blueprint-rocket"><Icon name="rocket" /></span
            ><span class="blueprint-star star-one"></span
            ><span class="blueprint-star star-two"></span>
          </div>
          <h3>{{ form.name || "等待命名" }}</h3>
          <p class="blueprint-domain">
            <strong>{{ domainName }}</strong
            ><span>.{{ options.baseDomain }}</span>
          </p>
          <div class="blueprint-divider"></div>
          <dl>
            <div>
              <dt><Icon name="blocks" />应用类型</dt>
              <dd>{{ form.application === "create" ? "新应用" : "更新已有应用" }}</dd>
            </div>
            <div>
              <dt><Icon name="git-branch" />部署分支</dt>
              <dd>main</dd>
            </div>
            <div>
              <dt><Icon name="folder" />代码仓库</dt>
              <dd class="blueprint-repo-dd" :title="form.repository || undefined">
                {{ shortRepository || "待填写" }}
              </dd>
            </div>
          </dl>
          <span class="blueprint-footnote">{{
            step === 4
              ? (options.executionEnabled ? "配置已就绪 · 可以部署" : "配置已就绪 · 等待执行环境")
              : "配置进度 " + progress + "%"
          }}</span>
        </aside>
      </div>
    </section>
  </main>
</template>

<style scoped>
.deployment-dot {
  color: #247cf0;
}
.deploy-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 28px;
}
.deploy-heading p {
  color: #71849c;
  font-size: 14px;
  margin: 5px 0 0;
}
.deploy-skill-download {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  border: 1px solid #c8d8eb;
  background: #f8fbffde;
  border-radius: 13px;
  padding: 13px 18px;
  color: #3e608a;
  font-size: 13px;
  box-shadow: 0 4px 12px #2e568a06;
  white-space: nowrap;
  text-decoration: none;
}
.deploy-skill-download:hover {
  background: #fff;
  border-color: #9fbbe0;
}
.deploy-skill-download:focus-visible {
  outline: 3px solid #2b72dc;
  outline-offset: 3px;
}
.deploy-skill-download .ui-icon {
  width: 18px;
  height: 18px;
}
.resource-card {
  padding: 22px 28px 18px;
  border: 1px solid #edcea1;
  border-left: 4px solid #d99b3a;
  border-radius: 20px;
  background: linear-gradient(110deg, #fff6e5, #fffdf8 66%, #fffaf0);
  box-shadow: 0 8px 25px #93662309;
  margin-bottom: 28px;
}
.resource-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.resource-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  background: #f8e6c4;
  color: #a06b18;
  border-radius: 12px;
}
.resource-icon .ui-icon {
  width: 21px;
  height: 21px;
}
.resource-eyebrow {
  color: #a77c3c;
  font-size: 10px;
  letter-spacing: 0.08em;
}
.resource-heading h2 {
  margin: 3px 0 0;
  font-size: 17px;
  font-weight: 650;
  color: #70532b;
}
.resource-badge {
  margin-left: auto;
  font-size: 11px;
  color: #8d7654;
}
.resource-values {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 20px 0 17px;
}
.resource-values > div {
  display: grid;
  grid-template-columns: 20px 1fr;
  align-items: center;
  column-gap: 8px;
  padding: 0 24px;
  border-left: 1px solid #d7b78055;
}
.resource-values > div:first-child {
  padding-left: 0;
  border: 0;
}
.resource-values .ui-icon {
  width: 17px;
  height: 17px;
  color: #aa8959;
}
.resource-values span {
  color: #8b775b;
  font-size: 12px;
}
.resource-values strong {
  grid-column: 2;
  font-size: 29px;
  font-weight: 650;
  color: #60492c;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
}
.resource-values small {
  font-size: 13px;
  font-weight: 500;
  margin-left: 3px;
  color: #8b775b;
}
.resource-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border-top: 1px solid #decaa755;
  padding-top: 13px;
  font-size: 12px;
  line-height: 1.7;
  color: #8c775a;
}
.resource-warning .ui-icon {
  flex-shrink: 0;
  width: 15px;
  height: 15px;
  margin-top: 3px;
}
.resource-warning strong {
  color: #946326;
  font-weight: 550;
}
.deploy-wizard {
  scroll-margin-top: var(--header-offset, 120px);
  background: #fcfdfff2;
  border: 1px solid white;
  border-radius: 26px;
  padding: 26px 32px 32px;
  box-shadow: 0 20px 50px -30px #284e7c40;
}
.wizard-progress-heading {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #8b9ab0;
}
.wizard-progress-heading > span:first-child {
  color: #56708d;
  font-weight: 600;
}
.wizard-progress-heading b {
  color: #2467d9;
  font-weight: 600;
}
.deploy-steps {
  position: relative;
  display: block;
  width: 100%;
  margin: 22px 0 30px;
  padding: 0;
}
.deploy-steps ol {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
}
.deploy-steps li {
  text-align: center;
  position: relative;
}
.deploy-steps button {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 0 8px;
  color: #92a0b4;
}
.deploy-steps button:disabled {
  cursor: not-allowed;
}
.step-node {
  display: grid;
  place-items: center;
  position: relative;
  width: 38px;
  height: 38px;
  border-radius: 13px;
  background: #edf2f9;
  border: 1px solid #dbe4ef;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 0 0 7px #fcfdff;
  transition:
    background 0.25s,
    box-shadow 0.25s;
}
.step-node .ui-icon {
  width: 18px;
  height: 18px;
}
.step-label {
  font-size: 13px;
  font-weight: 550;
}
.current button {
  color: #2d64b9;
}
.current .step-node {
  background: linear-gradient(145deg, #4385ef, #2865d5);
  border-color: #3672de;
  color: white;
  box-shadow:
    0 0 0 6px #eef4ff,
    0 5px 13px #2865d526;
}
.complete button {
  color: #557597;
}
.complete .step-node {
  background: #e7f1ff;
  border-color: #bbd4f4;
  color: #3075ce;
}
.step-track {
  position: absolute;
  height: 2px;
  background: #e2e9f2;
  left: 10%;
  right: 10%;
  top: 19px;
}
.step-track > span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #9bbfed, #3676dd);
  transition: width 0.4s ease;
}
.wizard-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 36px;
  border-top: 1px solid #e5ecf4;
  padding-top: 30px;
}
.deploy-form {
  display: block;
  padding: 0;
  margin: 0;
  min-width: 0;
  background: none;
  border: 0;
}
.deploy-form-stack { min-width: 0; }
.step-content {
  min-height: 320px;
}
.step-kicker {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.step-kicker > span:first-child {
  color: #829cbb;
  font-size: 12px;
  letter-spacing: 0.12em;
}
.required-chip {
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 5px;
  color: #b15d47;
  background: #fff0eb;
}
.review-chip {
  font-size: 10px;
  color: #4174b6;
}
.step-content h2 {
  font-size: 24px;
  color: #263f5e;
  font-weight: 600;
  margin: 0 0 7px;
  letter-spacing: -0.03em;
}
.step-content h2:focus {
  outline: none;
}
.step-description {
  color: #8190a4;
  font-size: 13px;
  margin: 0 0 26px;
}
.deploy-form label {
  display: block;
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 550;
  color: #425c7a;
}
.required-star {
  color: #b86751;
  margin-left: 4px;
}
.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.field-label-row label {
  margin: 0;
}
.scope-pills {
  display: inline-flex;
  padding: 3px;
  border-radius: 9px;
  background: #edf3fb;
  border: 1px solid #dce7f5;
}
.scope-pills button {
  padding: 4px 10px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: #5c7491;
  font-size: 12px;
  font-weight: 550;
  cursor: pointer;
}
.scope-pills button.active {
  background: #fff;
  color: #1f57b8;
  box-shadow: 0 1px 4px #1d478218;
}

.deploy-app-picker {
  position: relative;
  z-index: 20;
}
.app-picker-trigger {
  width: 100%;
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 10px 16px;
  border: 1px solid #cbd9eb;
  border-radius: 14px;
  background: #ffffff;
  color: #26415f;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 2px 10px #1f457808;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.app-picker-trigger:hover {
  border-color: #9ec0ea;
}
.app-picker-trigger.open,
.app-picker-trigger:focus-visible {
  border-color: #4f8ae8;
  box-shadow: 0 0 0 4px #3781ef17;
  outline: none;
}
.trigger-leading {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: #e8f1ff;
  color: #2463d8;
  flex-shrink: 0;
}
.trigger-leading.is-existing {
  background: linear-gradient(135deg, #2d73f5, #1b56ca);
  color: #fff;
}
.trigger-leading .ui-icon {
  width: 18px;
  height: 18px;
}
.trigger-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.trigger-copy strong {
  font-size: 15px;
  font-weight: 650;
  color: #1c3657;
  overflow-wrap: anywhere;
}
.trigger-copy small {
  font-size: 12px;
  color: #778da8;
  overflow-wrap: anywhere;
}
.trigger-chevron {
  color: #6f8aac;
  flex-shrink: 0;
}
.app-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.app-pill--online {
  background: #e1f6ec;
  color: #167656;
}
.app-pill--draft {
  background: #edf3fb;
  color: #4d6a8e;
}
.app-pill--owner {
  background: #f1f4f9;
  color: #5d7088;
}

.app-picker-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  border: 1px solid #cedef2;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 22px 50px -16px #183a6d38, 0 4px 14px #183a6d12;
  padding: 8px;
  overflow: hidden;
}
.picker-search-box {
  position: relative;
  margin-bottom: 6px;
}
.picker-search-box .ui-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 15px;
  height: 15px;
  color: #829ab6;
}
.picker-search-box input {
  width: 100%;
  height: 38px;
  padding: 0 12px 0 36px;
  border: 1px solid #dce7f5;
  border-radius: 10px;
  background: #f7faff;
  font-size: 13px;
  color: #244061;
  outline: none;
}
.picker-search-box input:focus {
  border-color: #72a5ec;
  background: #fff;
}
.picker-options-scroll {
  max-height: 296px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  display: grid;
  gap: 3px;
  padding-right: 2px;
}
.picker-options-scroll::-webkit-scrollbar {
  width: 6px;
}
.picker-options-scroll::-webkit-scrollbar-track {
  background: #f1f6fd;
  border-radius: 999px;
}
.picker-options-scroll::-webkit-scrollbar-thumb {
  background: #b7cde9;
  border-radius: 999px;
}
.picker-group-label {
  padding: 8px 10px 4px;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: #7c93ae;
}
.picker-option {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  text-align: left;
  color: inherit;
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease;
}
.picker-option:hover {
  background: #f2f7ff;
}
.picker-option.selected {
  background: #e8f2ff;
  border-color: #c5dcfa;
}
.picker-option--create {
  border-bottom: 1px solid #edf2fa;
  border-bottom-left-radius: 6px;
  border-bottom-right-radius: 6px;
  margin-bottom: 2px;
}
.option-badge {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: #edf3fc;
  color: #3f6ca8;
  flex-shrink: 0;
}
.option-badge.online {
  background: #e3f5ed;
  color: #197758;
}
.option-badge--create {
  background: #e5f0ff;
  color: #2161d8;
}
.option-badge--draft {
  background: #f2f5fa;
  color: #6b819c;
}
.option-badge .ui-icon {
  width: 16px;
  height: 16px;
}
.option-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.option-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.option-body strong {
  font-size: 14px;
  font-weight: 650;
  color: #1c3658;
}
.option-body small {
  font-size: 12px;
  color: #7a90ab;
  overflow-wrap: anywhere;
}
.option-check {
  width: 17px;
  height: 17px;
  color: #1e62da;
  flex-shrink: 0;
}
.picker-draft-toggle {
  margin-top: 4px;
  padding: 8px 12px;
  border: 0;
  border-top: 1px dashed #e3ecf7;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #6e85a1;
  font-size: 12px;
  cursor: pointer;
}
.picker-draft-toggle:hover {
  color: #275fb8;
}
.picker-draft-toggle .ui-icon {
  width: 14px;
  height: 14px;
  transition: transform 0.16s ease;
}
.picker-draft-toggle .ui-icon.rotated {
  transform: rotate(90deg);
}
.picker-draft-list {
  display: grid;
  gap: 3px;
}
.picker-no-match {
  margin: 12px 0;
  text-align: center;
  font-size: 12.5px;
  color: #7b90aa;
}

.deploy-input-wrap input {
  width: 100%;
  height: 54px;
  border: 1px solid #cbd9eb;
  border-radius: 12px;
  background: #fff;
  font: inherit;
  font-size: 15px;
  color: #294563;
  padding: 0 16px;
  outline: none;
  margin: 0;
}
.deploy-input-wrap input:focus {
  border-color: #70a0e2;
  box-shadow: 0 0 0 4px #3781ef12;
}
.deploy-input-wrap {
  position: relative;
}
.deploy-input-wrap > .ui-icon {
  width: 18px;
  height: 18px;
  position: absolute;
  left: 16px;
  top: 18px;
  color: #7d94b0;
}
.deploy-input-wrap > .ui-icon + input {
  padding-left: 46px;
}
.deploy-input-wrap input[aria-invalid="true"] {
  border-color: #cf8e78;
  background: #fffcfa;
}
.deploy-input-wrap input::placeholder {
  color: #a1afc0;
  font-size: 13px;
}
.name-input input {
  padding-right: 65px;
}
.name-input > span {
  position: absolute;
  right: 15px;
  top: 19px;
  color: #99a8bb;
  font-size: 12px;
}
.field-help {
  color: #7c8da3;
  font-size: 12px;
  line-height: 1.85;
  margin: 12px 0 0;
}
.deploy-form code {
  font-size: 12px;
  padding: 2px 5px;
  border-radius: 4px;
  background: #eaf0f8;
  color: #4c6b90;
}
.field-error {
  color: #ad5946;
  min-height: 20px;
  font-size: 12px;
  line-height: 1.6;
  margin: 8px 0 0;
}
.application-note {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 25px;
  padding: 18px;
  border: 1px dashed #ccdaea;
  background: #f4f8fe;
  border-radius: 12px;
}
.application-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  color: #6288ba;
  background: #e4eefb;
  border-radius: 10px;
}
.application-icon .ui-icon {
  width: 20px;
  height: 20px;
}
.application-note strong {
  color: #58718f;
  font-size: 13px;
  font-weight: 550;
}
.application-note p {
  color: #7d8fa6;
  font-size: 12.5px;
  line-height: 1.6;
  margin: 5px 0 0;
}
.application-note--existing {
  border-style: solid;
  border-color: #cbe0fa;
  background: linear-gradient(120deg, #eef5ff, #f8fbff);
  justify-content: space-between;
  flex-wrap: wrap;
}
.application-note-copy {
  flex: 1;
  min-width: 200px;
}
.application-live-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 9px;
  background: #fff;
  border: 1px solid #c5dbf8;
  color: #1f5ec9;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}
.application-live-btn:hover {
  background: #ebf3ff;
}
.application-live-btn .ui-icon {
  width: 13px;
  height: 13px;
}
.domain-preview {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #d3e2f5;
  border-radius: 12px;
  background: linear-gradient(110deg, #eaf3ff, #f8fbff);
  margin-top: 14px;
}
.domain-preview > .ui-icon {
  width: 21px;
  height: 21px;
  flex-shrink: 0;
  color: #7999c3;
}
.domain-preview > div {
  min-width: 0;
}
.domain-preview > div > span {
  font-size: 10px;
  color: #7b92b0;
}
.domain-preview p {
  margin: 4px 0 0;
  font-size: 14px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  color: #7c8fa8;
}
.domain-preview strong {
  color: #246add;
  font-weight: 650;
}
.name-input .invalid,
.domain-preview .invalid {
  color: #b15d47;
}
.wizard-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 22px;
  margin-top: 22px;
  border-top: 1px solid #e4ebf4;
}
.step-guidance {
  font-size: 12px;
  color: #97a7bb;
}
.previous-step {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #6e85a2;
  font-size: 13px;
  padding: 10px 0;
}
.next-step {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  min-width: 140px;
  padding: 13px 20px;
  border: 1px solid #2864d5;
  border-radius: 12px;
  background: linear-gradient(135deg, #3a7bef, #2561d2);
  color: white;
  font-size: 14px;
  font-weight: 550;
  box-shadow: 0 5px 14px #2865d526;
}
.next-step:hover {
  color: white;
  background: #245acc;
}
.next-step > .ui-icon {
  width: 18px;
  height: 18px;
}
.deployment-review {
  margin: 0;
}
.deployment-review > div {
  display: grid;
  grid-template-columns: 85px minmax(0, 1fr);
  gap: 12px;
  border-bottom: 1px solid #e8eef6;
  padding: 11px 0;
  font-size: 13px;
}
.deployment-review dt {
  color: #8a9bb0;
}
.deployment-review dd {
  color: #3d5879;
  margin: 0;
  overflow-wrap: anywhere;
}
.preview-mode,
.deployment-notice {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #8a99ab;
  margin: 15px 0 0;
}
.preview-mode .ui-icon,
.deployment-notice .ui-icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}
.deployment-notice {
  color: #577ca7;
  padding: 12px 14px;
  background: #edf4fd;
  border-radius: 9px;
}
.deploy-blueprint {
  position: sticky;
  top: calc(var(--header-offset, 112px) + 16px);
  align-self: start;
  overflow: hidden;
  min-width: 0;
  border-radius: 19px;
  padding: 23px;
  background:
    radial-gradient(ellipse at 110% 0%, #466b99, transparent 65%),
    linear-gradient(150deg, #203951, #182d46);
  color: #b5c8e0;
}
.deploy-blueprint::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 0.13;
  background-image: radial-gradient(#c8dbff 1px, transparent 1px);
  background-size: 18px 18px;
  pointer-events: none;
  mask-image: linear-gradient(#000, transparent 68%);
}
.blueprint-top {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  position: relative;
}
.blueprint-dot {
  width: 5px;
  height: 5px;
  background: #94bce9;
  border-radius: 50%;
  box-shadow: 0 0 0 4px #7cabe81a;
}
.blueprint-art {
  position: relative;
  display: grid;
  place-items: center;
  height: 140px;
}
.blueprint-orbit {
  position: absolute;
  width: 147px;
  height: 85px;
  border: 1px solid #adcff136;
  border-radius: 50%;
  transform: rotate(-30deg);
  box-shadow:
    0 0 0 15px #a5c8f007,
    0 0 0 30px #a5c8f005;
}
.blueprint-rocket {
  display: grid;
  place-items: center;
  width: 68px;
  height: 68px;
  border-radius: 20px;
  border: 1px solid #d3e5ff40;
  background: linear-gradient(135deg, #bedcff30, #bedcff0a);
  box-shadow:
    0 10px 25px #08182f20,
    inset 0 1px 0 #ffffff25;
  transform: rotate(-8deg);
}
.blueprint-rocket .ui-icon {
  width: 32px;
  height: 32px;
  color: #c7d8ef;
  stroke-width: 1.3;
}
.blueprint-star {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #92b5df;
}
.star-one {
  left: 20px;
  top: 82px;
}
.star-two {
  right: 25px;
  top: 37px;
  width: 3px;
  height: 3px;
}
.deploy-blueprint h3 {
  font-size: 23px;
  font-weight: 550;
  margin: 0;
  color: #e7f0fc;
  overflow-wrap: anywhere;
}
.blueprint-domain {
  font-size: 11px;
  line-height: 1.8;
  overflow-wrap: anywhere;
  margin: 8px 0 22px;
  color: #819bbd;
}
.blueprint-domain strong {
  color: #b3d2ff;
  font-weight: 500;
}
.blueprint-divider {
  height: 1px;
  background: linear-gradient(90deg, #a3c7ee30, transparent);
}
.deploy-blueprint dl {
  margin: 18px 0 25px;
}
.deploy-blueprint dl > div {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 13px 0;
  gap: 10px;
  font-size: 11px;
}
.deploy-blueprint dt {
  display: flex;
  gap: 7px;
  align-items: center;
  color: #8da8c7;
}
.deploy-blueprint dt .ui-icon {
  width: 13px;
  height: 13px;
}
.deploy-blueprint dd {
  margin: 0;
  color: #c6d7ed;
}
.blueprint-repo-dd {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.blueprint-footnote {
  font-size: 10px;
  color: #6f8aac;
}
.deploy-step-enter-active,
.deploy-step-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.18s ease;
}
.deploy-step-enter-from {
  opacity: 0;
  transform: translateX(9px);
}
.deploy-step-leave-to {
  opacity: 0;
  transform: translateX(-7px);
}
@media (max-width: 1000px) {
  .wizard-body {
    grid-template-columns: minmax(0, 1fr) 240px;
    gap: 24px;
  }
  .deploy-wizard {
    padding: 24px;
  }
}
@media (max-width: 760px) {
  .deploy-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
  }
  .deploy-skill-download {
    font-size: 12px;
    padding: 11px 14px;
  }
  .resource-card {
    padding: 18px 16px 14px;
  }
  .resource-badge {
    display: none;
  }
  .resource-values > div {
    padding: 0 12px;
    grid-template-columns: 1fr;
    gap: 3px;
  }
  .resource-values .ui-icon {
    display: none;
  }
  .resource-values strong {
    grid-column: 1;
    font-size: 23px;
  }
  .resource-values span {
    font-size: 10px;
  }
  .resource-values small {
    font-size: 10px;
    margin: 0;
  }
  .resource-heading h2 {
    font-size: 16px;
  }
  .wizard-body {
    grid-template-columns: 1fr;
    padding-top: 24px;
  }
  .deploy-blueprint {
    display: none;
  }
  .deploy-wizard {
    padding: 22px 18px;
    border-radius: 20px;
  }
  .step-label {
    font-size: 11px;
  }
  .step-node {
    width: 34px;
    height: 34px;
    border-radius: 11px;
    box-shadow: 0 0 0 4px #fcfdff;
  }
  .step-track {
    top: 17px;
  }
  .deploy-steps button {
    padding: 0 3px;
  }
  .step-content {
    min-height: 340px;
  }
  .step-content h2 {
    font-size: 22px;
  }
  .domain-preview {
    padding: 12px;
  }
  .domain-preview p {
    font-size: 12px;
  }
  .deploy-form input {
    font-size: 16px;
  }
  .next-step {
    min-width: 125px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .deploy-step-enter-active,
  .deploy-step-leave-active,
  .step-track > span,
  .step-node {
    transition: none;
  }
}
</style>

<style scoped>
.next-step:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
