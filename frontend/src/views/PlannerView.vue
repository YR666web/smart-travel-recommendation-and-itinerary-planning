<template>
  <div class="planner">
    <div class="intro">
      <p class="eyebrow">下一站，去哪里</p>
      <h1>想去哪儿？一起把行程排好</h1>
      <p>告诉我目的地、天数和预算，我会参考旅行攻略，安排每天怎么玩、吃什么，以及大概花多少钱。</p>
    </div>
    <div class="session-toolbar">
      <div><span class="toolbar-label">行程会话</span><strong>{{ session?.title || '新行程' }}</strong></div>
      <div class="session-actions">
        <el-select v-model="selectedSessionId" placeholder="打开历史行程" clearable filterable
          :disabled="loading" @change="openSession" @clear="startNew">
          <el-option v-for="item in sessions" :key="item.session_id" :label="`${item.title} · ${item.version}版 · ${formatDate(item.updated_at)}`" :value="item.session_id" />
        </el-select>
        <el-button :disabled="loading" @click="startNew">新建行程</el-button>
        <el-popconfirm v-if="session" title="删除这趟行程及全部版本？" confirm-button-text="删除" cancel-button-text="取消" @confirm="removeSession">
          <template #reference><el-button type="danger" plain :disabled="loading">删除</el-button></template>
        </el-popconfirm>
      </div>
    </div>
    <el-card v-if="!session" shadow="never" class="form-card">
      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <div class="fields">
          <el-form-item label="目的地"><el-input v-model="form.city" maxlength="64" placeholder="例如：杭州" /></el-form-item>
          <el-form-item label="天数"><el-input-number v-model="form.days" :min="1" :max="7" /></el-form-item>
          <el-form-item label="总预算（元）"><el-input-number v-model="form.budget" :min="100" :max="100000" :step="100" /></el-form-item>
        </div>
        <el-form-item label="旅行偏好"><el-input v-model="form.interests" maxlength="300" placeholder="例如：自然风景、美食，少走路" /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" size="large">{{ loading ? '正在规划…' : '生成行程' }}</el-button>
        <p class="hint">还没收录的目的地会尝试联网查找参考资料，并在结果中标明来源。</p>
      </el-form>
    </el-card>
    <el-alert v-if="failedRunId" type="error" :closable="false" class="failure" :title="`规划未完成 · 记录编号 ${failedRunId}`" description="可通过记录编号查看处理详情。" />

    <template v-if="session">
      <div class="conversation-head"><div><p class="eyebrow">一起把细节调好</p><h2>继续修改这趟行程</h2></div><span>{{ session.versions.length }} 个版本</span></div>
      <div class="version-list">
        <button v-for="item in session.versions" :key="item.version" type="button"
          class="version-item" :class="{ active: selectedVersion === item.version }"
          :aria-pressed="selectedVersion === item.version" @click="selectedVersion = item.version">
          <span class="version-number">{{ String(item.version).padStart(2, '0') }}</span>
          <span class="version-copy"><strong>{{ item.message }}</strong><small>{{ item.changes.join(' · ') }}</small></span>
          <span class="version-date">{{ formatDate(item.created_at) }}</span>
        </button>
      </div>
      <div v-if="session.questions?.length" class="question-history">
        <h3>对话记录</h3>
        <div v-for="(item, index) in session.questions" :key="index" class="question-pair">
          <div class="question-user"><span>你 · 第 {{ item.version }} 版</span><p>{{ item.question }}</p></div>
          <div class="question-answer"><span>行程助手</span><p>{{ item.answer.replaceAll('**', '') }}</p></div>
        </div>
      </div>
      <el-card shadow="never" class="followup-card">
        <div class="followup-title"><strong>继续问我，或修改行程</strong><span>提问直接解答；修改会生成新版本并重新核对预算与路线</span></div>
        <template v-if="isLatest">
          <el-input v-model="followupText" type="textarea" :rows="3" maxlength="500" show-word-limit
            :disabled="loading" placeholder="例如：为什么这样安排？或：第二天少走路，把预算降到 1200 元" />
          <div class="followup-actions">
            <div class="suggestions"><button v-for="suggestion in suggestions" :key="suggestion" type="button"
              :disabled="loading" @click="followupText = suggestion">{{ suggestion }}</button></div>
            <el-button type="primary" :loading="loading" :disabled="!followupText.trim()" @click="submitFollowup">{{ loading ? '正在处理…' : '发送' }}</el-button>
          </div>
        </template>
        <div v-else class="past-version">正在查看第 {{ selectedVersion }} 版。<button type="button" @click="selectedVersion = latestVersion">返回最新版继续修改</button></div>
      </el-card>
    </template>

    <template v-if="result">
      <el-alert v-if="result.source_mode !== 'local'" type="warning" show-icon :closable="false" class="source-note"
        :title="result.source_mode === 'web' ? '这座城市暂无本地攻略，本次行程参考联网资料。' : '本次行程结合了本地攻略与联网资料。'"
        description="网页内容和价格可能变化，出发前请到来源页面核实。" />
      <div class="result-header">
        <div><p class="eyebrow">第 {{ selectedVersion }} 版行程</p><h2>{{ result.plan.city }} · {{ result.plan.days.length }} 日行程</h2></div>
        <el-tag type="success">预估 ¥{{ result.plan.budget_total }}</el-tag>
      </div>
      <p class="summary">{{ result.plan.summary }}</p>
      <el-alert v-if="result.plan.budget_total > activeVersion.request.budget" title="预估费用超过预算，请调整偏好或预算。" type="warning" show-icon :closable="false" />
      <div class="day-grid">
        <el-card v-for="day in result.plan.days" :key="day.day" shadow="never" class="day-card">
          <div class="day-title"><strong>DAY {{ String(day.day).padStart(2, '0') }}</strong><span>约 ¥{{ day.estimated_cost }}</span></div>
          <p><b>上午</b>{{ day.morning }}</p><p><b>下午</b>{{ day.afternoon }}</p><p><b>晚上</b>{{ day.evening }}</p>
          <div v-if="mapDay(day.day)?.places?.length" class="map-details">
            <strong>地点与交通核验</strong>
            <div v-for="(place, index) in mapDay(day.day).places" :key="index">
              {{ place.requested_name }}
              <span v-if="place.poi" class="verified">✓ 地图定位：{{ place.poi.name }}{{ place.poi.address ? ` · ${place.poi.address}` : '' }}</span>
              <span v-else class="unverified">待核实</span>
            </div>
            <div v-for="(leg, index) in mapDay(day.day).legs" :key="`leg-${index}`" class="leg">
              {{ leg.from }} → {{ leg.to }}：{{ leg.route ? `${leg.route.mode === 'walking' ? '步行' : '公交'}约 ${leg.route.minutes} 分钟` : '交通未核验' }}
            </div>
          </div>
        </el-card>
      </div>
      <el-alert v-if="result.map_check" :type="result.map_check.status === 'checked' ? 'success' : 'warning'"
        show-icon :closable="false" class="map-note" :title="result.map_check.message">
        <ul v-if="result.map_check.issues.length"><li v-for="(issue, index) in result.map_check.issues" :key="index">{{ issue }}</li></ul>
      </el-alert>
      <el-card shadow="never" class="detail-card">
        <h3>预算与提醒</h3><p>{{ result.plan.budget_note }}</p>
        <ul><li v-for="(item, index) in result.plan.reminders" :key="index">{{ item }}</li></ul>
      </el-card>
      <el-card shadow="never" class="detail-card">
        <h3>引用资料</h3>
        <p v-if="!result.plan.cited_sources.length">本次回答未标注引用。</p>
        <div v-for="id in result.plan.cited_sources" :key="id" class="source">
          <template v-if="sourceById(id)">[{{ id }}]
            <a v-if="sourceById(id).source_url" :href="sourceById(id).source_url" target="_blank" rel="noopener noreferrer">{{ sourceById(id).source_file }}</a>
            <span v-else>{{ sourceById(id).source_file }}</span>
            · {{ sourceById(id).heading_path || '文档正文' }}
          </template>
        </div>
      </el-card>
      <el-card shadow="never" class="detail-card">
        <h3>规划过程 <small>{{ result.elapsed_ms }} ms · {{ result.usage.completion_tokens || 0 }} 输出 Token</small></h3>
        <el-timeline>
          <el-timeline-item v-for="(step, index) in result.steps" :key="index" :type="step.status === 'success' ? 'success' : 'danger'" :timestamp="`${step.elapsed_ms} ms`">
            <strong>{{ step.tool }}</strong> <span class="step-args">{{ step.arguments }}</span>
            <div class="step-result">{{ typeof step.result_summary === 'string' ? step.result_summary : JSON.stringify(step.result_summary) }}</div>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createPlanSession, deletePlanSession, getPlanSession, listPlanSessions, sendPlanFollowup } from '../api'

const form = reactive({ city: '杭州', days: 2, budget: 1500, interests: '自然风景与当地美食' })
const loading = ref(false)
const session = ref(null)
const sessions = ref([])
const selectedSessionId = ref('')
const selectedVersion = ref(0)
const followupText = ref('')
const failedRunId = ref('')
const suggestions = ['为什么这样安排？', '第二天少走路', '把预算降到 1200 元']
const latestVersion = computed(() => session.value?.versions.at(-1)?.version || 0)
const isLatest = computed(() => selectedVersion.value === latestVersion.value)
const activeVersion = computed(() => session.value?.versions.find((item) => item.version === selectedVersion.value))
const result = computed(() => activeVersion.value?.result || null)
const sourceById = (id) => result.value?.sources.find((source) => source.id === id)
const mapDay = (day) => result.value?.map_check?.days?.find((item) => item.day === day)
const formatDate = (value) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

function showSession(data) {
  session.value = data
  selectedSessionId.value = data.session_id
  selectedVersion.value = data.versions.at(-1).version
  Object.assign(form, data.versions.at(-1).request)
  localStorage.setItem('jingwen_plan_session_id', data.session_id)
}

async function refreshSessions() {
  try { sessions.value = (await listPlanSessions()).sessions } catch { /* 会话列表不可用时仍可新建 */ }
}

async function openSession(id) {
  if (!id) return
  loading.value = true
  try { showSession(await getPlanSession(id)) }
  catch { ElMessage.error('打开历史行程失败') }
  finally { loading.value = false }
}

function startNew() {
  session.value = null
  selectedSessionId.value = ''
  selectedVersion.value = 0
  followupText.value = ''
  failedRunId.value = ''
  localStorage.removeItem('jingwen_plan_session_id')
}

async function removeSession() {
  if (!session.value) return
  loading.value = true
  try {
    await deletePlanSession(session.value.session_id)
    startNew()
    await refreshSessions()
    ElMessage.success('行程已删除')
  } catch { ElMessage.error('删除行程失败') }
  finally { loading.value = false }
}

onMounted(async () => {
  await refreshSessions()
  const saved = localStorage.getItem('jingwen_plan_session_id')
  if (saved) {
    try { showSession(await getPlanSession(saved)) }
    catch { localStorage.removeItem('jingwen_plan_session_id') }
  }
})

async function submit() {
  if (!form.city.trim()) return ElMessage.warning('请输入目的地')
  loading.value = true
  failedRunId.value = ''
  try {
    showSession(await createPlanSession({ city: form.city.trim(), days: form.days, budget: form.budget, interests: form.interests.trim() }))
    await refreshSessions()
  } catch (error) {
    failedRunId.value = error.response?.data?.detail?.run_id || ''
    ElMessage.error(error.response?.data?.detail?.message || '规划失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function submitFollowup() {
  const message = followupText.value.trim()
  if (!message || !isLatest.value) return
  loading.value = true
  failedRunId.value = ''
  try {
    showSession(await sendPlanFollowup(session.value.session_id, { message, base_version: latestVersion.value }))
    followupText.value = ''
    await refreshSessions()
  } catch (error) {
    failedRunId.value = error.response?.data?.detail?.run_id || ''
    const detail = error.response?.data?.detail
    ElMessage.error(detail?.message || (typeof detail === 'string' ? detail : '修改失败，上一版行程已保留'))
    if (error.response?.status === 409) await openSession(session.value.session_id)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.planner { max-width: 1120px; margin: 0 auto; padding: 12px 12px 60px; color: #263238; }
.intro { margin: 18px 0 28px; }
.eyebrow { color: #24736b; font-size: 12px; font-weight: 700; letter-spacing: .14em; }
h1 { font-size: clamp(28px, 4vw, 42px); margin: 7px 0 10px; letter-spacing: -.04em; }
h2 { margin: 4px 0; font-size: 26px; }
h3 { margin: 0 0 12px; }
.intro > p:last-child, .summary { color: #60716d; line-height: 1.7; }
.hint { color: #81918d; font-size: 12px; margin: 12px 0 0; }
.session-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 22px 0 16px; padding: 17px 20px; border: 1px solid #dae4df; border-radius: 14px; background: #f4f8f5; }
.session-toolbar > div:first-child { display: flex; flex-direction: column; gap: 4px; }
.session-toolbar strong { font-size: 16px; }
.toolbar-label { color: #637973; font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.session-actions { display: flex; gap: 10px; align-items: center; }
.session-actions :deep(.el-select) { width: 225px; }
.conversation-head { display: flex; justify-content: space-between; align-items: end; margin: 30px 0 14px; }
.conversation-head h2 { margin: 0; }
.conversation-head > span { color: #789087; font-size: 13px; }
.version-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 9px; }
.version-item { box-sizing: border-box; min-width: 0; width: 100%; display: flex; gap: 16px; align-items: center; padding: 14px 17px; border: 1px solid #dce6df; border-radius: 12px; background: #fff; color: #263238; text-align: left; cursor: pointer; transition: border-color .2s, background .2s, transform .2s; }
.version-item:hover { border-color: #77aaa0; transform: translateY(-1px); }
.version-item.active { border-color: #24736b; background: #eff7f4; }
.version-number { color: #24736b; font-family: Georgia, serif; font-size: 22px; line-height: 1; }
.version-copy { min-width: 0; display: flex; flex: 1; flex-direction: column; gap: 4px; }
.version-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-copy small { color: #6c817a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-date { color: #82938d; font-size: 12px; white-space: nowrap; }
.question-history { margin-top: 21px; }
.question-history h3 { color: #315c54; font-size: 15px; margin-bottom: 12px; }
.question-pair { display: grid; gap: 7px; margin-bottom: 17px; }
.question-user, .question-answer { max-width: 88%; padding: 11px 14px; border-radius: 12px; font-size: 13px; line-height: 1.6; }
.question-user { justify-self: end; background: #e4f1eb; color: #285c52; }
.question-answer { justify-self: start; background: #f3f6f3; color: #344b43; }
.question-pair span { font-size: 11px; color: #788d83; }
.question-pair p { margin: 4px 0 0; white-space: pre-wrap; }
.followup-card { margin-top: 16px; border: 1px solid #c9dfd5; border-radius: 14px; background: #fbfdfb; }
.followup-title { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.followup-title strong { color: #1c5c56; font-size: 17px; }
.followup-title span { color: #81918d; font-size: 12px; }
.followup-actions { display: flex; align-items: center; justify-content: space-between; gap: 15px; margin-top: 12px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 7px; }
.suggestions button { padding: 6px 10px; border: 1px solid #d5e5dc; border-radius: 999px; background: #fff; color: #3c756c; font-size: 12px; cursor: pointer; }
.suggestions button:hover { background: #eaf5ee; }
.suggestions button:disabled { opacity: .5; cursor: default; }
.past-version { color: #667e76; font-size: 13px; }
.past-version button { padding: 0; border: 0; background: none; color: #24736b; font-weight: 700; cursor: pointer; }
.form-card, .detail-card, .day-card { border-color: #dae4df; border-radius: 14px; }
.fields { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 16px; }
.fields :deep(.el-input-number) { width: 100%; }
.result-header { display: flex; align-items: center; justify-content: space-between; margin-top: 38px; }
.result-header .el-tag { font-size: 16px; padding: 18px; }
.day-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin: 20px 0; }
.day-title { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e5ede9; padding-bottom: 12px; color: #24736b; }
.day-card p { display: flex; gap: 12px; line-height: 1.6; margin-bottom: 0; }
.day-card b { min-width: 34px; }
.detail-card { margin: 16px 0; }
.failure { margin-top: 18px; }
.source-note { margin-top: 20px; }
.map-note { margin: 16px 0; }
.map-note ul { margin: 6px 0 0; padding-left: 20px; }
.map-details { margin-top: 15px; padding-top: 12px; border-top: 1px solid #e5ede9; font-size: 12px; line-height: 1.8; color: #60716d; }
.map-details strong { color: #24736b; }
.verified { color: #24736b; }
.unverified { color: #b36b20; }
.leg { padding-left: 10px; color: #466078; }
.detail-card p, li { line-height: 1.7; }
.source { padding: 7px 0; border-bottom: 1px solid #eef2f0; }
.step-args { color: #667; font-size: 12px; word-break: break-all; }
.step-result { color: #60716d; margin-top: 6px; font-size: 13px; }
small { color: #80918a; font-weight: normal; font-size: 12px; }
@media (max-width: 700px) { .fields { grid-template-columns: 1fr; gap: 0; } .result-header { align-items: flex-start; } .session-toolbar, .followup-actions { align-items: stretch; flex-direction: column; } .session-actions, .session-actions :deep(.el-select) { width: 100%; } .version-date { display: none; } .followup-title { align-items: flex-start; flex-direction: column; gap: 4px; } }
</style>
