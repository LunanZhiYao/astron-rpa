<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { message } from 'ant-design-vue'
import { isEmpty } from 'lodash-es'

import i18next from '@/plugins/i18next'
import BUS from '@/utils/eventBus'

import { autoArrangeByChatCompletions } from '@/api/robot'
import { engineAtomicByKey } from '@/data/engineAtomicRef'
import { useFlowStore } from '@/stores/useFlowStore'
import { useProcessStore } from '@/stores/useProcessStore'
import { addAtomData, deleteAtomData } from '@/views/Arrange/components/flow/hooks/useFlow'
import { Group, GroupEnd } from '@/views/Arrange/config/atomKeyMap'
import { getSelected } from '@/views/Arrange/utils/contextMenu'

interface AIArrangeNode {
  key: string
  id?: string
  version?: string
  alias?: string
  params?: Record<string, any>
  inputList?: Array<{ key: string, value: any, show?: boolean }>
  outputList?: Array<{ key: string, value: any, show?: boolean }>
  advanced?: Array<{ key: string, value: any, show?: boolean }>
  exception?: Array<{ key: string, value: any, show?: boolean }>
}

/** 顶层 JSON：{ "nodes": [...], "reply": "..." }，无 plan/steps/action/position */
interface AIArrangeResponse {
  nodes: AIArrangeNode[]
  reply: string
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  nodes?: AIArrangeNode[]
  pending?: boolean
  thinking?: boolean
  failed?: boolean
  toolLogs?: string[]
}

const AI_REQUEST_TIMEOUT_MSG = '服务器繁忙，请稍后重试'
const loading = ref(false)
const userInput = ref('')
const inputRef = ref<any>(null)
const chatList = ref<ChatMessage[]>([])
/** 最近一次 AI 写入后画布上的节点 id（用于上下文选区兜底） */
const lastAppliedNodeIds = ref<string[]>([])
const llmMessages = ref<Array<{ role: 'system' | 'user' | 'assistant', content: string }>>([
  {
    role: 'system',
    content: `你是 RPA 设计器自动编排助手。
请严格输出 JSON，不要 markdown。
输出格式（nodes + reply）：
{
  "nodes": [
    {
      "key": "组件key",
      "id": "可选id",
      "version": "可选version",
      "alias": "可选别名",
      "inputList": [{"key":"参数key","value":[{"type":"var|other|python","value":"参数值"}]}],
      "outputList": [{"key":"输出key","value":[{"type":"var","value":"变量名"}]}],
      "advanced": [{"key":"__delay_before__","value":[{"type":"other","value":0}]}],
      "exception": [{"key":"__skip_err__","value":"exit"}]
    }
  ],
  "reply": "给用户的简短说明"
}
语义：nodes 表示清空画布后要写入的整条流程的最终顺序（全量替换）；禁止局部增量描述。
规则：
1) nodes 必须是替换后的全量节点序列。
2) key 须为有效组件：以用户消息里 components 的 key 为准，不得臆造。
3) components 里有两种上下文：contextLevel=full|lite。full 包含完整参数 schema；lite 仅摘要信息。优先从 full 组件中选型与填参。
4) full 组件参数包含：key/title/type/formType/required/default/options/tip/example。你要优先根据 comment、tip、options 生成合法参数。
5) 参数必须按数据库节点格式返回：inputList/outputList/advanced/exception。
6) 参数 key 必须来自组件 schema；若字段有 options，优先使用 options.value。
7) 循环结构使用引擎原生节点对：Code.ForStep ... Code.ForEnd，不要臆造任何嵌套结构。
8) 禁止使用编组（Group/GroupEnd）组件；不要包含编组节点。
9) 参数值使用统一结构："value":[{"type":"var|other|python","value":"..."}]；纯枚举/布尔/数字字段可直接返回标量值。
10) 条件结构同理，使用引擎已有起止节点（若组件库存在对应 End 节点则必须成对出现），不要自定义层级数据结构。
11) IF/条件判断类组件必须按结构化字段拆分：对象一(left/object_1)、关系(operator/relation/logic)、对象二(right/object_2)。禁止把完整条件句（如 "A > B"）填到“关系”字段。
12) 对所有“多字段语义”参数（如条件判断、行列范围、开始/结束）必须分别填入对应字段，不能只填其中一个字段。
13) Excel 参数必须严格使用组件 schema 中的 key，禁止臆造键（如 filePath/readOnly/outputVar/hasHeader/rowIndex/colIndex/color 等）。
14) Excel 链路约束：先 Excel.open_excel 得到 excel 对象，后续 Excel.read_excel/edit_excel/design_cell_type/save_excel/close_excel 必须传 excel 对象，不要重复传 file_path。
15) Excel.read_excel 必须显式给 read_range（cell/row/column/area/all）及对应字段；Excel.edit_excel 必须给 edit_range + start_row/start_col + value。
16) Excel.design_cell_type 设置字体颜色时使用 font_color（如红色），并按 design_type+cell_position/range_position/row/col 定位，不使用不存在的 color/rowIndex/colIndex。
17) components 已融合设计器组件全集与引擎参数原文；若同一字段在不同来源有差异，以 full 组件中的参数 schema 为准。
18) 用户消息中的 current_flow 会携带各节点在设计器里已填写参数与 _line 行号。当用户要改参数、纠正或检查配置时，须结合该现状在返回的节点参数中给出修正后的全量值。
19) 能用流程变量时优先使用 type="var"（如 [{"type":"var","value":"price"}]），仅在确实需要复杂表达式时再用 type="python"；不要使用 \${...} 形式。
20) 用户可能在需求中用 @flow[起始行-结束行] 指定多个范围。每个 @flow[...] 都与其附近语义绑定（例如“删除@flow[12-18]，把@flow[21-21]改为不等于”），不要只按出现顺序机械处理。`,
  },
])

const flowStore = useFlowStore()
const processStore = useProcessStore()
const canSend = computed(() => !!userInput.value.trim() && !loading.value)

function createId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function getNativeInputEl(): HTMLTextAreaElement | null {
  return inputRef.value?.resizableTextArea?.textArea ?? null
}

function insertTextAtCursor(text: string) {
  const token = String(text || '').trim()
  if (!token)
    return
  const el = getNativeInputEl()
  if (!el) {
    userInput.value = `${userInput.value}${userInput.value ? ' ' : ''}${token}`.trim()
    return
  }
  const start = el.selectionStart ?? userInput.value.length
  const end = el.selectionEnd ?? userInput.value.length
  const before = userInput.value.slice(0, start)
  const after = userInput.value.slice(end)
  const shouldPrefixSpace = before.length > 0 && !/\s$/.test(before)
  const shouldSuffixSpace = after.length > 0 && !/^\s/.test(after)
  const insert = `${shouldPrefixSpace ? ' ' : ''}${token}${shouldSuffixSpace ? ' ' : ''}`
  userInput.value = `${before}${insert}${after}`
  const nextPos = before.length + insert.length
  queueMicrotask(() => {
    el.focus()
    el.setSelectionRange(nextPos, nextPos)
  })
}

function handleInsertAiArrangeTag(tagText: string) {
  insertTextAtCursor(tagText)
}

onMounted(() => {
  BUS.$on('insertAiArrangeTag', handleInsertAiArrangeTag)
})

onBeforeUnmount(() => {
  BUS.$off('insertAiArrangeTag', handleInsertAiArrangeTag)
})

/** 调试：对话框内展示可复制 nodes */
function formatNodesForDebug(nodes: AIArrangeNode[] | undefined) {
  if (!nodes?.length)
    return ''
  try {
    return JSON.stringify(nodes, null, 2)
  }
  catch {
    return ''
  }
}

async function copyNodesJsonText(text: string) {
  const t = (text || '').trim()
  if (!t)
    return
  try {
    await navigator.clipboard.writeText(t)
    message.success('已复制 nodes JSON')
  }
  catch {
    message.error('复制失败，请在下方文本框内手动全选复制')
  }
}

function selectTextareaAll(ev: MouseEvent) {
  const el = ev.target as HTMLTextAreaElement
  el?.select?.()
}

function cleanJsonText(rawText: string) {
  return rawText
    .trim()
    .replace(/^```json\s*/i, '')
    .replace(/^```\s*/i, '')
    .replace(/\s*```$/, '')
    .trim()
}

function mergeDbStyleParamList(
  params: Record<string, any>,
  list?: Array<{ key: string, value: any }>,
) {
  if (!Array.isArray(list))
    return
  for (const item of list) {
    if (item?.key)
      params[item.key] = item.value
  }
}

function mapNodeParamLists(node: AIArrangeNode): AIArrangeNode {
  const mergedParams: Record<string, any> = { ...(node.params || {}) }
  mergeDbStyleParamList(mergedParams, node.inputList)
  mergeDbStyleParamList(mergedParams, node.outputList)
  mergeDbStyleParamList(mergedParams, node.advanced)
  mergeDbStyleParamList(mergedParams, node.exception)
  return {
    ...node,
    params: mergedParams,
  }
}

function parseAIResponse(rawText: string): AIArrangeResponse {
  const pureText = cleanJsonText(rawText)
  const parsed = JSON.parse(pureText) as Record<string, unknown>
  const nodes = Array.isArray(parsed.nodes) ? parsed.nodes as AIArrangeNode[] : undefined
  const reply = typeof parsed.reply === 'string' ? parsed.reply : ''
  if (!nodes?.length || !reply) {
    throw new Error(i18next.t('arrange.aiArrangeInvalidJson'))
  }
  return { nodes: nodes.map(node => mapNodeParamLists(node)), reply }
}

interface PlanValidationResult {
  ok: boolean
  errors: string[]
  diagnostics?: Array<{
    path: string
    message: string
    expected?: {
      key?: string
      type?: string
      required?: boolean
      options?: Array<{ value: any, label: string }>
      example?: any
    }
  }>
}

function validateNodesStrict(nodes: AIArrangeNode[]): PlanValidationResult {
  const errors: string[] = []
  const diagnostics: PlanValidationResult['diagnostics'] = []
  const componentList = getComponentList()
  const componentMap = new Map(componentList.map(item => [item.key, item]))
  const normalizeValidationAlias = (rawKey: string) => {
    const raw = String(rawKey || '').trim()
    const compact = raw.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]/g, '')
    const aliasMap: Record<string, string> = {
      excelobj: 'excel',
      excel_object: 'excel',
      sheetname: 'sheet_name',
      filepath: 'file_path',
      column: 'col',
      columns: 'col',
      rowindex: 'start_row',
      colindex: 'start_col',
      listvar: 'list_data',
      itemvar: 'item',
      outputexcel: 'open_excel_obj',
      outputdata: 'read_excel_contents',
    }
    return aliasMap[compact] || raw
  }

  const checkNode = (node: AIArrangeNode, path: string) => {
    const comp = componentMap.get(node.key)
    if (!comp) {
      errors.push(`${path}: 组件 ${node.key} 不在可用列表`)
      diagnostics?.push({
        path,
        message: `组件 ${node.key} 不在可用列表`,
      })
      return
    }
    const allowedParamKeys = new Set([...(comp.inputList || []).map(i => i.key), ...(comp.outputList || []).map(i => i.key)])
    const paramSpecMap = new Map([...(comp.inputList || []), ...(comp.outputList || [])].map(i => [i.key, i]))
    const hasReliableSchema = allowedParamKeys.size > 0
    const params = node.params || {}
    Object.keys(params).forEach((k) => {
      const normalizedKey = normalizeValidationAlias(k)
      const paramKey = allowedParamKeys.has(k) ? k : normalizedKey
      const isKnownParam = hasReliableSchema ? allowedParamKeys.has(paramKey) : true
      if (!isKnownParam) {
        errors.push(`${path}: 参数 ${k} 不是 ${node.key} 的合法字段`)
        diagnostics?.push({
          path: `${path}.params.${k}`,
          message: `参数 ${k} 非法`,
          expected: {
            key: '合法参数 key',
            type: 'one_of_component_schema',
            required: false,
            options: [...paramSpecMap.values()].slice(0, 20).map(item => ({ value: item.key, label: `${item.key} (${item.title || item.type || 'unknown'})` })),
            example: [...paramSpecMap.values()].slice(0, 3).map(item => ({ [item.key]: item.example ?? item.default ?? '' })),
          },
        })
      }
      else {
        const spec = paramSpecMap.get(paramKey)
        const options = (spec?.options || []).map((o: any) => o?.value).filter((v: any) => v !== undefined)
        if (options.length > 0) {
          const rawValue = (params as any)[k]
          const isObjectLike = rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)
          const canCheck = !isObjectLike
          if (canCheck) {
            const value = typeof rawValue === 'string' ? rawValue.trim() : rawValue
            if (!options.includes(value)) {
              errors.push(`${path}: 参数 ${k} 的值 ${JSON.stringify(rawValue)} 不在可选值中`)
              diagnostics?.push({
                path: `${path}.params.${k}`,
                message: `参数 ${k} 枚举值非法`,
                expected: {
                  key: k,
                  type: spec?.type || 'enum',
                  required: !!spec?.required,
                  options: (spec?.options || []).slice(0, 20),
                  example: (spec?.options || [])[0]?.value,
                },
              })
            }
          }
        }
      }
    })

    if (node.key === 'Code.If') {
      if (typeof (params as any).left === 'object' || typeof (params as any).right === 'object') {
        errors.push(`${path}: Code.If 的 left/right 必须是字符串表达式`)
        diagnostics?.push({
          path: `${path}.params`,
          message: 'Code.If left/right 类型错误',
          expected: {
            key: 'left/right',
            type: 'string_expression',
            required: true,
            example: {
              left: [{ type: 'var', value: 'row_col_6' }],
              relation: 'equals',
              right: [{ type: 'var', value: 'price_list_city' }],
            },
          },
        })
      }
    }
    if (node.key === 'Excel.read_excel') {
      if (!(params as any).excel)
        errors.push(`${path}: Excel.read_excel 缺少 excel 对象参数`)
      if (!(params as any).excel) {
        diagnostics?.push({
          path: `${path}.params.excel`,
          message: '缺少 excel 对象',
          expected: {
            key: 'excel',
            type: 'ExcelObj',
            required: true,
            example: [{ type: 'var', value: 'excel_obj' }],
          },
        })
      }
      if (!(params as any).read_range)
        errors.push(`${path}: Excel.read_excel 缺少 read_range`)
      if (!(params as any).read_range) {
        diagnostics?.push({
          path: `${path}.params.read_range`,
          message: '缺少读取范围',
          expected: {
            key: 'read_range',
            type: 'enum',
            required: true,
            options: [
              { value: 'cell', label: '单元格' },
              { value: 'row', label: '行' },
              { value: 'column', label: '列' },
              { value: 'area', label: '区域' },
              { value: 'all', label: '已编辑区域' },
            ],
            example: 'area',
          },
        })
      }
    }
    if (node.key === 'Excel.edit_excel') {
      if (!(params as any).excel)
        errors.push(`${path}: Excel.edit_excel 缺少 excel 对象参数`)
      if (!(params as any).excel) {
        diagnostics?.push({
          path: `${path}.params.excel`,
          message: '缺少 excel 对象',
          expected: {
            key: 'excel',
            type: 'ExcelObj',
            required: true,
            example: [{ type: 'var', value: 'excel_obj' }],
          },
        })
      }
      if (!(params as any).edit_range)
        errors.push(`${path}: Excel.edit_excel 缺少 edit_range`)
      if (!(params as any).edit_range) {
        diagnostics?.push({
          path: `${path}.params.edit_range`,
          message: '缺少编辑范围',
          expected: {
            key: 'edit_range',
            type: 'enum',
            required: true,
            options: [
              { value: 'row', label: '行' },
              { value: 'column', label: '列' },
              { value: 'area', label: '区域' },
              { value: 'cell', label: '单元格' },
            ],
            example: 'column',
          },
        })
      }
      if ((params as any).value === undefined || (params as any).value === null || (params as any).value === '')
        errors.push(`${path}: Excel.edit_excel 缺少 value`)
      if ((params as any).value === undefined || (params as any).value === null || (params as any).value === '') {
        diagnostics?.push({
          path: `${path}.params.value`,
          message: '缺少写入值',
          expected: {
            key: 'value',
            type: 'string|list',
            required: true,
            example: [{ type: 'python', value: 'bill_row.col_K * row.col_C' }],
          },
        })
      }
    }
    if (node.key === 'Excel.design_cell_type') {
      if (!(params as any).excel)
        errors.push(`${path}: Excel.design_cell_type 缺少 excel 对象参数`)
      if (!(params as any).design_type)
        errors.push(`${path}: Excel.design_cell_type 缺少 design_type`)
      const designType = String((params as any).design_type ?? '').trim()
      if (designType && !['cell', 'row', 'column', 'area'].includes(designType)) {
        errors.push(`${path}: Excel.design_cell_type 的 design_type=${designType} 非法`)
        diagnostics?.push({
          path: `${path}.params.design_type`,
          message: 'design_type 必须是 cell/row/column/area 之一',
          expected: {
            key: 'design_type',
            type: 'enum',
            required: true,
            options: [
              { value: 'cell', label: '单元格' },
              { value: 'row', label: '行' },
              { value: 'column', label: '列' },
              { value: 'area', label: '区域' },
            ],
            example: 'column',
          },
        })
      }
    }
  }
  nodes.forEach((node, idx) => checkNode(node, `nodes[${idx}]`))
  return { ok: errors.length === 0, errors, diagnostics }
}

function isTimeoutError(error: unknown) {
  const err = (error || {}) as Record<string, any>
  const code = err.code
  const msg = String(err.message ?? '')
  const status = err.response?.status
  const detail = String(err.response?.data?.detail ?? '')
  return code === 'ECONNABORTED'
    || /timeout/i.test(msg)
    || status === 504
    || detail.includes('超时')
}

function getComponentList() {
  const normalizeParamList = (list: any[] = []) => {
    const extractDefaultValue = (raw: any) => {
      if (Array.isArray(raw) && raw.length > 0 && typeof raw[0] === 'object' && raw[0] !== null && Object.prototype.hasOwnProperty.call(raw[0], 'value')) {
        return raw[0].value
      }
      return raw
    }

    const normalizeOptions = (options: any[] = []) => {
      return options
        .map((opt) => {
          const value = opt?.value
          const label = opt?.label
          if (value === undefined && label === undefined)
            return null
          return {
            value,
            label: label ?? String(value ?? ''),
          }
        })
        .filter(Boolean)
        .slice(0, 20)
    }

    const normalizeExample = (param: any) => {
      const tip = String(param?.tip || '')
      const match = tip.match(/(如|例如|例：|示例[:：]?)\s*([A-Za-z0-9_:\-./\\\[\], ]{1,80})/)
      if (match?.[2])
        return match[2].trim()
      return undefined
    }

    return list.map((param) => {
      return {
        key: param?.key || '',
        title: param?.title || '',
        type: param?.types || param?.type || '',
        formType: param?.formType?.type || '',
        required: !!param?.required,
        comment: param?.subTitle || param?.comment || '',
        tip: param?.tip || '',
        default: extractDefaultValue(param?.value),
        options: normalizeOptions(param?.options || param?.formType?.params?.options || []),
        example: normalizeExample(param),
      }
    })
  }

  return processStore.atomicTreeDataFlat
    .filter(item => !!item.key)
    .map((item) => {
      const engineRef = engineAtomicByKey[item.key]
      const uiInputList = normalizeParamList(item.inputList)
      const uiOutputList = normalizeParamList(item.outputList)
      const mergedInputList = uiInputList.length > 0 ? uiInputList : normalizeParamList(engineRef?.inputList as any[] || [])
      const mergedOutputList = uiOutputList.length > 0 ? uiOutputList : normalizeParamList(engineRef?.outputList as any[] || [])
      return {
        key: item.key,
        name: item.title || item.name || engineRef?.title || item.key,
        comment: item.comment || item.desc || item.subTitle || engineRef?.comment || '',
        inputList: mergedInputList,
        outputList: mergedOutputList,
      }
    })
}

function buildComponentContext(requirement: string) {
  const fullList = getComponentList()
  const requirementText = (requirement || '').toLowerCase()
  const tokens = Array.from(new Set((requirementText.match(/[\u4e00-\u9fa5a-zA-Z0-9_.-]+/g) || []).filter(token => token.length >= 2)))
  const selectedFlowKeys = new Set(getSelectedFlowContent().map(item => item.key).filter(Boolean))

  const scoreComponent = (item: ReturnType<typeof getComponentList>[number]) => {
    let score = 0
    const keyText = item.key.toLowerCase()
    const nameText = String(item.name || '').toLowerCase()
    const commentText = String(item.comment || '').toLowerCase()
    const paramText = [
      ...(item.inputList || []).map(p => `${p.key} ${p.title} ${p.tip} ${(p.options || []).map((o: any) => `${o?.value ?? ''} ${o?.label ?? ''}`).join(' ')}`),
      ...(item.outputList || []).map(p => `${p.key} ${p.title} ${p.tip}`),
    ].join(' ').toLowerCase()

    if (selectedFlowKeys.has(item.key))
      score += 120
    if (requirementText.includes(keyText))
      score += 100
    if (requirementText.includes(nameText))
      score += 80

    for (const token of tokens) {
      if (!token)
        continue
      if (keyText.includes(token))
        score += 30
      if (nameText.includes(token))
        score += 20
      if (commentText.includes(token))
        score += 12
      if (paramText.includes(token))
        score += 6
    }

    return score
  }

  const ranked = fullList
    .map(item => ({ item, score: scoreComponent(item) }))
    .sort((a, b) => b.score - a.score)

  const TOP_FULL = 50
  const TOP_LITE = 120
  const fullComponents = ranked
    .filter((entry, idx) => entry.score > 0 || idx < 25)
    .slice(0, TOP_FULL)
    .map(entry => ({
      ...entry.item,
      contextLevel: 'full',
    }))
  const fullKeySet = new Set(fullComponents.map(item => item.key))
  const liteComponents = ranked
    .filter(entry => !fullKeySet.has(entry.item.key))
    .slice(0, TOP_LITE)
    .map(entry => ({
      key: entry.item.key,
      name: entry.item.name,
      comment: entry.item.comment,
      contextLevel: 'lite',
    }))

  return {
    components: [...fullComponents, ...liteComponents],
    contextMeta: {
      total: fullList.length,
      fullCount: fullComponents.length,
      liteCount: liteComponents.length,
    },
  }
}

/** 汇总画布上单步节点的表单取值，供发给 AI（与组件 input/output/advanced/exception 中的 value 一致） */
function collectAtomParamMap(atom: RPA.Atom): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const lists = [
    atom.inputList || [],
    atom.outputList || [],
    atom.advanced || [],
    atom.exception || [],
  ]
  for (const list of lists) {
    for (const item of list) {
      if (item?.key)
        out[item.key] = item.value
    }
  }
  return out
}

function getSelectedFlowContent() {
  const ids = getSelected()
  if (isEmpty(ids))
    return []
  return flowStore.simpleFlowUIData
    .map((item, idx) => ({
      _line: idx + 1,
      id: item.id,
      key: item.key,
      alias: item.alias ?? item.anotherName ?? '',
      params: collectAtomParamMap(item),
    }))
    .filter(item => ids.includes(item.id))
}

function getCurrentFlowContent() {
  return flowStore.simpleFlowUIData.map((item, idx) => ({
    _line: idx + 1,
    id: item.id,
    key: item.key,
    alias: item.alias ?? item.anotherName ?? '',
    params: collectAtomParamMap(item),
  }))
}

async function applyNodes(nodes: AIArrangeNode[]) {
  const componentSet = new Set(getComponentList().map(item => item.key))
  const validNodes = nodes.filter(node => node?.key && componentSet.has(node.key) && ![Group, GroupEnd].includes(node.key as any))
  if (isEmpty(validNodes)) {
    message.warning(i18next.t('arrange.aiArrangeNoMatchedNode'))
    return
  }

  // 全量替换：每次应用前清空当前流程，再从头插入 AI 返回的完整流程
  let insertIndex = 0
  const allIds = flowStore.simpleFlowUIData.map(item => item.id)
  if (!isEmpty(allIds)) {
    deleteAtomData(allIds)
    await new Promise(resolve => setTimeout(resolve, 0))
  }

  let cursor = insertIndex
  const insertedIds: string[] = []
  const applyNodeParams = (atomId: string, params?: Record<string, any>) => {
    if (!params)
      return
    const atom = flowStore.simpleFlowUIData.find(item => item.id === atomId)
    if (!atom)
      return

    const formItems = [...(atom.inputList || []), ...(atom.advanced || []), ...(atom.outputList || []), ...(atom.exception || [])]
    const toSnakeCase = (input: string) => {
      return input
        .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
        .replace(/[-\s]+/g, '_')
        .toLowerCase()
    }
    const normalizeKey = (input: string) => toSnakeCase(input).replace(/[^a-z0-9_]/g, '')
    const compactKey = (input: string) => normalizeKey(input).replace(/_/g, '')

    const parseA1Range = (value: string) => {
      const text = value.trim().toUpperCase()
      const m = text.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/)
      if (!m)
        return null
      return {
        start_col: m[1],
        start_row: Number(m[2]),
        end_col: m[3],
        end_row: Number(m[4]),
      }
    }

    const normalizeParamAlias = (inputKey: string, atomKey: string) => {
      const raw = (inputKey || '').trim()
      const aliasMap: Record<string, string> = {
        // 常见中文别名
        行: 'row',
        列: 'col',
        起始行: 'start_row',
        结束行: 'end_row',
        起始列: 'start_col',
        结束列: 'end_col',
        单元格: 'cell',
        单元格位置: 'cell_position',
        范围: 'range_position',
        区域: 'range_position',
        // 常见英文/驼峰别名
        line: 'row',
        rows: 'row',
        column: 'col',
        columns: 'col',
        startrow: 'start_row',
        endrow: 'end_row',
        startcolumn: 'start_col',
        endcolumn: 'end_col',
        startcol: 'start_col',
        endcol: 'end_col',
        cellposition: 'cell_position',
        cellpos: 'cell_position',
        cellrange: 'range_position',
        range: 'range_position',
        // 字典设置值常见别名
        字典: 'dict_data',
        字典数据: 'dict_data',
        dict: 'dict_data',
        dictionary: 'dict_data',
        key: 'dict_key',
        键: 'dict_key',
        键key: 'dict_key',
        value: 'value',
        值: 'value',
        // 数学计算常见别名
        左值: 'left',
        左侧值: 'left',
        左操作数: 'left',
        leftvalue: 'left',
        右值: 'right',
        右侧值: 'right',
        右操作数: 'right',
        rightvalue: 'right',
        运算符: 'operator',
        操作符: 'operator',
        operatorsymbol: 'operator',
        返回值处理: 'handle_method',
        结果处理: 'handle_method',
        roundingmethod: 'handle_method',
        保留位数: 'precision',
        // Excel 常见别名
        excelobj: 'excel',
        excel_object: 'excel',
        sheetname: 'sheet_name',
        filepath: 'file_path',
        // 循环常见别名
        listvar: 'list_data',
        itemvar: 'item',
        // 条件常见别名
        object1: 'left',
        object2: 'right',
      }
      const compact = raw.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]/g, '')
      const mapped = aliasMap[compact] || raw
      if ((raw === 'output_var' || raw === 'outputVar') && atom.outputList?.length) {
        return atom.outputList[0].key
      }
      // read_excel 中 area/range 不是合法字段，需要转为 start/end 组合，单字段映射在后续处理
      if (atomKey === 'Excel.read_excel' && ['area', 'range', 'range_position'].includes(compact))
        return 'area'
      return mapped
    }

    const buildCandidates = (inputKey: string) => {
      const raw = normalizeParamAlias(inputKey, atom.key)
      const snake = toSnakeCase(raw)
      const normalized = normalizeKey(raw)
      const compact = compactKey(raw)
      return Array.from(new Set([raw, raw.toLowerCase(), snake, normalized, compact]))
    }

    const findTargetItem = (rawKey: string) => {
      const candidates = buildCandidates(rawKey)
      // 1) 精确匹配
      let target = formItems.find(item => candidates.includes(item.key))
      if (target)
        return target
      // 2) 规范化后匹配
      target = formItems.find(item => candidates.includes(normalizeKey(item.key)))
      if (target)
        return target
      // 3) 使用字段标题匹配（如“键（key）”“运算符”）
      target = formItems.find(item => candidates.includes(normalizeKey(item.title || '')))
      if (target)
        return target
      // 4) 去下划线紧凑匹配（filePath -> filepath -> file_path）
      const aliased = normalizeParamAlias(rawKey, atom.key)
      target = formItems.find(item => compactKey(item.key) === compactKey(aliased))
      if (target)
        return target
      return formItems.find(item => compactKey(item.title || '') === compactKey(aliased))
    }

    const normalizeExcelEnum = (value: any) => {
      if (typeof value !== 'string')
        return value
      const map: Record<string, string> = {
        单元格: 'cell',
        行: 'row',
        列: 'column',
        区域: 'area',
        已编辑区域: 'all',
      }
      const cleaned = value.trim()
      return map[cleaned] || cleaned.toLowerCase()
    }

    const normalizeCellOrRange = (value: any) => {
      if (typeof value !== 'string')
        return value
      return value
        .trim()
        .replace(/[，、；\s]+/g, '')
        .replace(/[~\-至]/g, ':')
        .replace(/[：]/g, ':')
        .toUpperCase()
    }

    const normalizeByField = (fieldKey: string, value: any) => {
      const key = fieldKey.toLowerCase()
      if (typeof value === 'string') {
        const boolMap: Record<string, boolean> = {
          是: true,
          否: false,
          true: true,
          false: false,
        }
        if (Object.prototype.hasOwnProperty.call(boolMap, value.trim().toLowerCase())) {
          return boolMap[value.trim().toLowerCase()]
        }
        if (Object.prototype.hasOwnProperty.call(boolMap, value.trim())) {
          return boolMap[value.trim()]
        }
      }
      if (['edit_range', 'read_range', 'design_type', 'copy_range_type', 'delete_range_excel', 'select_type'].includes(key)) {
        return normalizeExcelEnum(value)
      }
      if (['operator'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          加: '+',
          减: '-',
          乘: '*',
          除: '/',
          plus: '+',
          minus: '-',
          multiply: '*',
          divide: '/',
        }
        const v = value.trim().toLowerCase()
        return map[v] || map[value.trim()] || value
      }
      if (['handle_method'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          四舍五入: 'round',
          向上取整: 'ceil',
          向下取整: 'floor',
          不做操作: 'none',
          round: 'round',
          ceil: 'ceil',
          floor: 'floor',
          none: 'none',
        }
        return map[value.trim()] || map[value.trim().toLowerCase()] || value
      }
      if (['font_type'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          维持原状: 'no_change',
          粗体: 'bold',
          斜体: 'italic',
          粗斜体: 'bold_italic',
          常规: 'normal',
        }
        return map[value.trim()] || value
      }
      if (['horizontal_align'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          维持原状: 'no_change',
          默认常规: 'default',
          左对齐: 'left-aligned',
          右对齐: 'right-aligned',
          居中对齐: 'center',
          填充: 'padding',
          两端对齐: 'aligned_both_sides',
          跨列居中: 'center_cross_column',
          分散对齐: 'distributed_align',
        }
        return map[value.trim()] || value
      }
      if (['vertical_align'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          维持原状: 'no_change',
          靠上: 'up',
          居中: 'middle',
          靠下: 'down',
          两端对齐: 'aligned_both_sides',
          分散对齐: 'distributed_align',
        }
        return map[value.trim()] || value
      }
      if (['numberformat'].includes(key) && typeof value === 'string') {
        const map: Record<string, string> = {
          常规: 'G/通用格式',
          数字: '0.00',
          货币: '¥#,##0.00',
          短日期: 'yyyy/m/d',
          长日期: 'yyyy年mm月dd日',
          时间: 'h:mm:ss AM/PM',
          百分比: '0.00%',
          分数: '# ?/?',
          科学记数: '0.00E+00',
          自定义: 'other',
        }
        return map[value.trim()] || value
      }
      if (['cell', 'cell_position', 'coordinate', 'cell_location', 'start_location', 'insert_pos'].includes(key)) {
        return normalizeCellOrRange(value)
      }
      if (['range_position', 'data_range', 'range_location', 'merge_cell_range', 'split_cell_range', 'comment_range', 'sheet_range'].includes(key)) {
        return normalizeCellOrRange(value)
      }
      if (['row', 'start_row', 'end_row'].includes(key) && typeof value === 'string' && /^-?\d+$/.test(value.trim())) {
        return Number(value)
      }
      if (['col', 'start_col', 'end_col', 'column'].includes(key) && typeof value === 'string') {
        const v = value.trim()
        return /^-?\d+$/.test(v) ? Number(v) : v.toUpperCase()
      }
      return value
    }

    const appliedParamKeys = new Set<string>()
    Object.entries(params).forEach(([paramKey, rawValue]) => {
      const target = findTargetItem(paramKey)
      if (!target)
        return

      appliedParamKeys.add(paramKey)
      const currentValue = target.value as any
      let normalizedValue = normalizeByField(target.key, rawValue)
      // INPUT_VARIABLE_* 表单结构统一使用 [{ type, value }]
      if (
        Array.isArray(currentValue)
        && currentValue.length > 0
        && typeof currentValue[0] === 'object'
        && currentValue[0] !== null
        && Object.prototype.hasOwnProperty.call(currentValue[0], 'value')
      ) {
        normalizedValue = rawValue
      }
      flowStore.setFormItemValue(target.key, normalizedValue, atomId)
    })

    // IF 条件组件兼容：AI 常返回 left/relation/right，但组件可能使用 logic_text 结构字段
    const hasIfTriplet = ['left', 'relation', 'right'].every(key => Object.prototype.hasOwnProperty.call(params, key))
    const hasAppliedIfTriplet = ['left', 'relation', 'right'].every(key => appliedParamKeys.has(key))
    if (hasIfTriplet && !hasAppliedIfTriplet) {
      const logicField = formItems.find(item => ['logic_text', 'logicText', 'condition', 'condition_text'].includes(item.key))
      if (logicField) {
        const relationRaw = String((params as Record<string, any>).relation ?? '').trim()
        const relationMap: Record<string, string> = {
          equals: '==',
          equal: '==',
          '==': '==',
          not_equals: '!=',
          notEqual: '!=',
          '!=': '!=',
          gt: '>',
          '>': '>',
          gte: '>=',
          '>=': '>=',
          lt: '<',
          '<': '<',
          lte: '<=',
          '<=': '<=',
          contains: 'in',
          in: 'in',
          not_contains: 'notIn',
          notin: 'notIn',
          notIn: 'notIn',
        }
        const normalizedLogic = relationMap[relationRaw] || relationMap[relationRaw.toLowerCase()] || relationRaw || '=='
        const leftValueRaw = (params as Record<string, any>).left
        const rightValueRaw = (params as Record<string, any>).right
        const leftValue = typeof leftValueRaw === 'object' && leftValueRaw
          ? (leftValueRaw.object_1 ?? leftValueRaw.left ?? JSON.stringify(leftValueRaw))
          : leftValueRaw
        const rightValue = typeof rightValueRaw === 'object' && rightValueRaw
          ? (rightValueRaw.object_2 ?? rightValueRaw.right ?? JSON.stringify(rightValueRaw))
          : rightValueRaw

        const logicTextValue = [
          {
            conditionalValue: leftValue,
            logic: normalizedLogic,
            reducedValue: rightValue,
            inputLogicOperator: '&&',
          },
        ]
        flowStore.setFormItemValue(logicField.key, logicTextValue, atomId)
      }
    }

    // Excel.read_excel area 兼容：支持 AI 返回 area/range 为 A1:B2
    if (atom.key === 'Excel.read_excel') {
      const areaRaw = (params as Record<string, any>).area ?? (params as Record<string, any>).range ?? (params as Record<string, any>).range_position
      if (typeof areaRaw === 'string') {
        const areaParsed = parseA1Range(areaRaw)
        if (areaParsed) {
          flowStore.setFormItemValue('read_range', 'area', atomId)
          flowStore.setFormItemValue('start_col', areaParsed.start_col, atomId)
          flowStore.setFormItemValue('start_row', areaParsed.start_row, atomId)
          flowStore.setFormItemValue('end_col', areaParsed.end_col, atomId)
          flowStore.setFormItemValue('end_row', areaParsed.end_row, atomId)
        }
      }
    }

    // Excel.edit_excel 兼容：edit_range=L/M -> column + start_col
    if (atom.key === 'Excel.edit_excel') {
      const editRangeRaw = String((params as Record<string, any>).edit_range ?? '').trim()
      if (/^[A-Za-z]+$/.test(editRangeRaw)) {
        flowStore.setFormItemValue('edit_range', 'column', atomId)
        flowStore.setFormItemValue('start_col', editRangeRaw.toUpperCase(), atomId)
      }
    }

    // Excel.design_cell_type 兼容：design_type=font_color + range_position=L/M
    if (atom.key === 'Excel.design_cell_type') {
      const rangePos = String((params as Record<string, any>).range_position ?? '').trim()
      if (/^[A-Za-z]+$/.test(rangePos)) {
        flowStore.setFormItemValue('design_type', 'column', atomId)
        flowStore.setFormItemValue('col', rangePos.toUpperCase(), atomId)
      }
    }
  }

  const runtimeNodes = validNodes
  const insertNode = async (node: AIArrangeNode, startCursor: number): Promise<number> => {
    const atomList = await addAtomData(node.key, startCursor, false, false)
    if (!atomList?.length) {
      return startCursor
    }

    if (node.alias?.trim()) {
      flowStore.setFormItemValue('anotherName', node.alias.trim(), atomList[0].id)
    }
    applyNodeParams(atomList[0].id, node.params)
    insertedIds.push(...atomList.map(item => item.id))

    return startCursor + atomList.length
  }

  for (const node of runtimeNodes) {
    cursor = await insertNode(node, cursor)
  }

  if (isEmpty(insertedIds)) {
    message.warning(i18next.t('arrange.aiArrangeNoMatchedNode'))
    return
  }

  lastAppliedNodeIds.value = insertedIds
  processStore.setSavingType(processStore.activeProcessId, processStore.saveProject, true, false, 1000)
  message.success(i18next.t('arrange.aiArrangeSuccess'))
}

async function sendMessage() {
  const requirement = userInput.value.trim()
  if (!requirement || loading.value)
    return
  const { components: componentList, contextMeta } = buildComponentContext(requirement)
  if (isEmpty(componentList)) {
    message.warning(i18next.t('arrange.aiArrangeNoComponents'))
    return
  }

  userInput.value = ''
  chatList.value.push({
    id: createId(),
    role: 'user',
    content: requirement,
  })
  const pendingMsg: ChatMessage = {
    id: createId(),
    role: 'assistant',
    content: '',
    thinking: true,
    toolLogs: [],
  }
  chatList.value.push(pendingMsg)

  loading.value = true
  try {
    llmMessages.value.push({
      role: 'user',
      content: JSON.stringify({
        requirement,
        components: componentList,
        component_context_meta: contextMeta,
        current_flow: getCurrentFlowContent(),
      }),
    })
    const raw = await autoArrangeByChatCompletions({
      messages: llmMessages.value,
    })
    const aiResponse = parseAIResponse(raw)
    llmMessages.value.push({
      role: 'assistant',
      content: raw,
    })

    pendingMsg.content = aiResponse.reply
    pendingMsg.nodes = aiResponse.nodes
    pendingMsg.pending = false
    pendingMsg.thinking = false
    if (aiResponse.nodes?.length) {
      pendingMsg.toolLogs ||= []
      pendingMsg.toolLogs.push('开始执行计划。')
      await confirmApply(pendingMsg)
    }
  }
  catch (error) {
    if (isTimeoutError(error)) {
      message.error(AI_REQUEST_TIMEOUT_MSG)
      pendingMsg.content = AI_REQUEST_TIMEOUT_MSG
    }
    else {
      const err = (error || {}) as Record<string, any>
      const errMsg = String(err?.response?.data?.detail || err?.message || i18next.t('arrange.aiArrangeFailed'))
      message.error(errMsg)
      pendingMsg.content = errMsg
    }
    pendingMsg.failed = true
    pendingMsg.thinking = false
  }
  finally {
    loading.value = false
  }
}

function clearSession() {
  userInput.value = ''
  chatList.value = []
  lastAppliedNodeIds.value = []
  const systemMsg = llmMessages.value.find(msg => msg.role === 'system')
  llmMessages.value = systemMsg ? [systemMsg] : []
}

async function autoRepairPlan(
  msg: ChatMessage,
  validation: PlanValidationResult,
  mode: 'repair_invalid_plan' | 'regenerate_from_scratch' = 'repair_invalid_plan',
) {
  const latestUserRequirement = [...chatList.value].reverse().find(i => i.role === 'user')?.content || ''
  const { components: componentList, contextMeta } = buildComponentContext(latestUserRequirement)
  const repairPrompt = {
    task: mode,
    requirement: latestUserRequirement,
    validation_errors: validation.errors,
    validation_diagnostics: validation.diagnostics || [],
    invalid_nodes: msg.nodes,
    components: componentList,
    component_context_meta: contextMeta,
    current_flow: getCurrentFlowContent(),
    rule: mode === 'repair_invalid_plan'
      ? '仅返回修正后的完整 JSON，保持 nodes + reply 顶层结构。必须严格通过校验。'
      : '忽略历史错误结果，重新从需求与组件 schema 生成“最小可执行且可校验通过”的完整 nodes JSON。',
  }
  llmMessages.value.push({
    role: 'user',
    content: JSON.stringify(repairPrompt),
  })
  const raw = await autoArrangeByChatCompletions({
    messages: llmMessages.value,
  })
  const aiResponse = parseAIResponse(raw)
  llmMessages.value.push({
    role: 'assistant',
    content: raw,
  })
  if (!aiResponse.nodes?.length) {
    throw new Error(i18next.t('arrange.aiArrangeInvalidJson'))
  }
  msg.nodes = aiResponse.nodes
  msg.content = aiResponse.reply || msg.content
}

async function confirmApply(msg: ChatMessage) {
  if (!msg.nodes?.length)
    return
  msg.toolLogs ||= []
  const maxRepairTimes = 4
  for (let i = 0; i < maxRepairTimes; i += 1) {
    const validation = validateNodesStrict(msg.nodes)
    if (validation.ok)
      break
    const diagTips = (validation.diagnostics || []).slice(0, 2).map(d => `${d.path}: ${d.message}${d.expected?.example ? `（示例: ${JSON.stringify(d.expected.example)}）` : ''}`)
    msg.toolLogs.push(`校验失败（第 ${i + 1} 次）：${validation.errors.slice(0, 2).join('；')}`)
    if (diagTips.length)
      msg.toolLogs.push(`修正要求：${diagTips.join('；')}`)
    const repairMode = i < 2 ? 'repair_invalid_plan' : 'regenerate_from_scratch'
    msg.toolLogs.push(repairMode === 'repair_invalid_plan'
      ? '正在自动请求 AI 修正计划...'
      : '连续失败，正在让 AI 从头重生成最小可执行流程...')
    try {
      await autoRepairPlan(msg, validation, repairMode)
      msg.toolLogs.push(repairMode === 'repair_invalid_plan'
        ? 'AI 已返回修正计划，继续校验。'
        : 'AI 已返回重生成计划，继续校验。')
    }
    catch (error) {
      const err = (error || {}) as Record<string, any>
      const errMsg = String(err?.response?.data?.detail || err?.message || i18next.t('arrange.aiArrangeFailed'))
      msg.toolLogs.push(`自动修正失败：${errMsg}`)
      message.error(errMsg)
      return
    }
  }
  const finalValidation = validateNodesStrict(msg.nodes)
  if (!finalValidation.ok) {
    const finalErr = `计划校验仍未通过：${finalValidation.errors.slice(0, 3).join('；')}`
    msg.toolLogs.push(finalErr)
    msg.toolLogs.push('已达到最大自动修正次数，进入降级策略：强制写入设计器。')
    message.warning(finalErr)
  }
  msg.toolLogs.push(finalValidation.ok ? '计划校验通过，开始应用。' : '以降级模式开始应用当前计划。')
  await applyNodes(msg.nodes)
  msg.toolLogs.push('已完成应用。')
  msg.pending = false
}

</script>

<template>
  <div class="ai-arrange-panel h-full flex flex-col bg-[#fff] dark:bg-[#1f1f1f]">
    <div class="px-4 py-3 border-b border-[#00000014] dark:border-[#ffffff1f]">
      <div class="flex items-center justify-between">
        <div class="font-medium">{{ $t('arrange.aiArrangeTitle') }}</div>
        <a-button size="small" @click="clearSession">
          清空会话
        </a-button>
      </div>
      <div class="text-xs text-[#00000073] dark:text-[#ffffff73] mt-1">
        {{ $t('arrange.aiArrangePanelTip') }}
      </div>
    </div>

    <div class="flex-1 overflow-auto px-4 py-3 space-y-3">
      <div class="text-xs text-[#ff0000e2] dark:text-[#ff0000e2]">
        {{ $t('arrange.aiArrangeEmptyChatTip') }}
      </div>

      <div
        v-for="item in chatList"
        :key="item.id"
        class="rounded-md px-3 py-2 text-sm"
        :class="item.role === 'user'
          ? 'bg-[#f0f5ff] dark:bg-[#27324a] ml-6'
          : 'bg-[#f6f6f6] dark:bg-[#2a2a2a] mr-6'"
      >
        <div class="text-xs mb-1 opacity-70">
          {{ item.role === 'user' ? $t('arrange.aiArrangeRoleUser') : $t('arrange.aiArrangeRoleAI') }}
        </div>
        <div class="whitespace-pre-wrap break-words">{{ item.content }}</div>
        <div v-if="item.thinking" class="mt-2 text-xs opacity-70 flex items-center gap-2">
          <a-spin size="small" />
          <span>{{ $t('arrange.aiArrangeThinking') }}</span>
        </div>

        <div v-if="item.nodes?.length" class="mt-2 space-y-1">
          <div class="flex items-center justify-between gap-2 flex-wrap">
            <span class="text-xs opacity-80">{{ $t('arrange.aiArrangePlanSummary', { count: item.nodes.length }) }}</span>
            <a-button
              size="small"
              type="link"
              class="!p-0 !h-auto text-xs"
              @click="copyNodesJsonText(formatNodesForDebug(item.nodes))"
            >
              复制 nodes JSON
            </a-button>
          </div>
          <textarea
            readonly
            class="nodes-debug-json w-full font-mono text-[11px] leading-relaxed p-2 rounded border border-[#00000014] dark:border-[#ffffff26] bg-[#fafafa] dark:bg-[#141414] text-[#000000e0] dark:text-[#ffffffd9] resize-y min-h-[140px] max-h-[min(420px,50vh)] outline-none select-all"
            rows="14"
            :value="formatNodesForDebug(item.nodes)"
            @focus="selectTextareaAll"
            @click="selectTextareaAll"
          />
        </div>
        <div v-if="item.toolLogs?.length" class="mt-2 text-[11px] leading-4 opacity-70 border-l-2 border-[#00000026] dark:border-[#ffffff33] pl-2 space-y-1">
          <div v-for="(log, idx) in item.toolLogs" :key="`${item.id}_tool_${idx}`">
            {{ log }}
          </div>
        </div>
      </div>
    </div>

    <div class="p-3 border-t border-[#00000014] dark:border-[#ffffff1f]">
      <a-textarea
        ref="inputRef"
        v-model:value="userInput"
        :rows="4"
        :maxlength="1000"
        :placeholder="$t('arrange.aiArrangeInputPlaceholder')"
      />
      <div class="mt-2 flex items-center justify-between">
        <span v-if="loading" class="text-xs text-[#00000073] dark:text-[#ffffff73]">{{ $t('arrange.aiArrangeLoading') }}</span>
        <span v-else />
        <a-button type="primary" :loading="loading" :disabled="!canSend" @click="sendMessage">
          {{ $t('send') }}
        </a-button>
      </div>
    </div>
  </div>
</template>

