// Merge atomic sections from engine/components/*/config.yaml into one JSON keyed by component key.
// Run from web-app: node scripts/generate-engine-atomic-ref.mjs
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import yaml from 'yaml'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../../../..')
const componentsDir = path.join(repoRoot, 'engine/components')

function pickList(list) {
  if (!Array.isArray(list))
    return []
  return list.map(item => ({
    key: item.key,
    title: item.title,
    tip: item.tip,
    subTitle: item.subTitle,
    types: item.types,
    required: item.required,
    options: item.options || item.formType?.params?.options,
    formType: item.formType?.type,
  }))
}

function stripAtomicEntry(entry, source) {
  if (!entry || typeof entry !== 'object')
    return entry
  return {
    title: entry.title,
    comment: entry.comment,
    helpManual: entry.helpManual,
    icon: entry.icon,
    inputList: pickList(entry.inputList),
    outputList: pickList(entry.outputList),
    _source: source,
  }
}

const merged = {}
const dirs = fs.readdirSync(componentsDir, { withFileTypes: true })

for (const d of dirs) {
  if (!d.isDirectory())
    continue
  const yamlPath = path.join(componentsDir, d.name, 'config.yaml')
  if (!fs.existsSync(yamlPath))
    continue
  const text = fs.readFileSync(yamlPath, 'utf8')
  const doc = yaml.parse(text)
  const atomic = doc?.atomic
  if (!atomic || typeof atomic !== 'object')
    continue
  for (const [key, val] of Object.entries(atomic)) {
    if (merged[key]) {
      console.warn(`[generate-engine-atomic-ref] duplicate key "${key}" in ${d.name}, skipped`)
      continue
    }
    merged[key] = stripAtomicEntry(val, d.name)
  }
}

const outDir = path.join(__dirname, '../src/data')
fs.mkdirSync(outDir, { recursive: true })
const outPath = path.join(outDir, 'engineAtomicComponents.json')
fs.writeFileSync(outPath, `${JSON.stringify(merged)}\n`)

const size = fs.statSync(outPath).size
console.log(`[generate-engine-atomic-ref] wrote ${Object.keys(merged).length} keys (${size} bytes) -> ${outPath}`)
