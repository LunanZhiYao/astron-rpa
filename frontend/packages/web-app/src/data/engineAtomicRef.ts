/**
 * 引擎侧 atomic 定义（由 engine/components 下各子包的 config.yaml 合并生成，见 scripts/generate-engine-atomic-ref.mjs）
 * 用于 AI 编排校验/修正时对齐官方参数 key 与 comment。
 */
import engineAtomicComponents from './engineAtomicComponents.json'

export interface EngineAtomicParamMeta {
  key: string
  title?: string
  tip?: string
  subTitle?: string
  types?: string
  required?: boolean
  options?: unknown
  formType?: string
}

/** 单组件在 yaml 中的摘要（含来源包名 _source） */
export interface EngineAtomicEntry {
  title?: string
  comment?: string
  helpManual?: string
  icon?: string
  inputList: EngineAtomicParamMeta[]
  outputList: EngineAtomicParamMeta[]
  _source: string
}

/** 以组件 key 为索引的全表（291+ 键） */
export const engineAtomicByKey = engineAtomicComponents as Record<string, EngineAtomicEntry>

/** 按 key 子集取出供 Prompt 使用的引擎原文，缺失 key 不会出现 */
export function pickEngineAtomicRef(keys: Iterable<string>): Record<string, EngineAtomicEntry> {
  const out: Record<string, EngineAtomicEntry> = {}
  for (const k of keys) {
    const e = engineAtomicByKey[k]
    if (e)
      out[k] = e
  }
  return out
}

/** 递归收集 AI 节点树中出现的组件 key */
export function collectKeysFromAITree(nodes: Array<{ key?: string, children?: unknown }>): string[] {
  const acc: string[] = []
  function walk(n: { key?: string, children?: unknown }) {
    if (typeof n.key === 'string' && n.key.trim())
      acc.push(n.key)
    const ch = n.children
    if (Array.isArray(ch)) {
      for (const c of ch)
        walk(c as { key?: string, children?: unknown })
    }
  }
  for (const n of nodes)
    walk(n)
  return acc
}
