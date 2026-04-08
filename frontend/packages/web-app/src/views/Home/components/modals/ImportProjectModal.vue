<script setup lang="ts">
import { NiceModal } from '@rpa/components'
import { message, Upload } from 'ant-design-vue'
import type { FormInstance, RuleObject, UploadProps } from 'ant-design-vue'
import { useTranslation } from 'i18next-vue'
import { reactive, ref } from 'vue'

interface FormState {
  name: string
}

const props = defineProps<{
  title?: string
  name?: string
  defaultName?: string
  rules?: RuleObject[]
  onConfirm: (name: string, importData: AnyObj) => Promise<void>
}>()

const modal = NiceModal.useModal()
const { t } = useTranslation()

const loading = ref(false)
const formRef = ref<FormInstance>()
const formState = reactive<FormState>({ name: '' })
const importData = ref<AnyObj | null>(null)
const fileName = ref('')

const beforeUpload: UploadProps['beforeUpload'] = (file) => {
  const isJson = file.name.endsWith('.json')
  if (!isJson) {
    message.error(t('common.onlyJsonFile'))
    return false
  }

  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const content = e.target?.result as string
      const data = JSON.parse(content)
      importData.value = data
      fileName.value = file.name
      formState.name = data.robotName || file.name.replace('.json', '')
      message.success(t('common.fileParsedSuccess'))
    } catch {
      message.error(t('common.fileParseFailed'))
    }
  }
  reader.readAsText(file)
  return false
}

async function handleOk() {
  if (!importData.value) {
    message.error(t('common.pleaseSelectFile'))
    return
  }

  const valid = await formRef.value?.validate()
  if (!valid)
    return

  loading.value = true
  try {
    await props.onConfirm(formState.name, importData.value)
  }
  finally {
    loading.value = false
  }
}

function handleRemove() {
  importData.value = null
  fileName.value = ''
}
</script>

<template>
  <a-modal
    v-bind="NiceModal.antdModal(modal)"
    :width="400"
    :title="title"
    :confirm-loading="loading"
    @ok="handleOk"
  >
    <a-form
      ref="formRef"
      :model="formState"
      autocomplete="off"
      layout="vertical"
    >
      <a-form-item :label="$t('common.selectFile')">
        <a-upload
          :file-list="[]"
          :before-upload="beforeUpload"
          accept=".json"
        >
          <a-button>
            {{ $t('common.selectJsonFile') }}
          </a-button>
        </a-upload>
        <div v-if="fileName" class="mt-2 flex items-center gap-2">
          <span class="text-green-500">{{ fileName }}</span>
          <a-button type="link" size="small" @click="handleRemove">
            {{ $t('common.remove') }}
          </a-button>
        </div>
      </a-form-item>
      <a-form-item
        :label="name"
        name="name"
        :rules="[
          { required: true, message: t('common.enterPlaceholder', { name }) },
          ...(props.rules || []),
        ]"
      >
        <a-input v-model:value="formState.name" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>
