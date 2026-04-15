<script setup lang="ts">
import { Auth } from '@rpa/components/auth'
import { message } from 'ant-design-vue'
import { useTranslation } from 'i18next-vue'
import { storeToRefs } from 'pinia'
import { ref } from 'vue'

import { createConfigParam } from '@/api/atom'
import { saveSmartComp } from '@/api/component'
import { checkProjectNum, createProject, getDefaultName } from '@/api/project'
import { addElement, addElementGroup, addGlobalVariable, addProcess, addProcessPyCode, addPyPackageApi, flowSave, genProcessName, genProcessPyCodeName, getProcessAndCodeList, getPyPackageListApi, renameProcess, renameProcessPyCode, saveProcessPyCode } from '@/api/resource'
import { addComponentUse, removeComponent } from '@/api/robot'
import { ARRANGE } from '@/constants/menu'
import { useRoutePush } from '@/hooks/useCommonRoute'
import { useAppConfigStore } from '@/stores/useAppConfig'
import { useUserStore } from '@/stores/useUserStore'
import type { AnyObj } from '@/types/common'
import { importProjectModal, newProjectModal } from '@/views/Home/components/modals'

import Banner from '../components/Banner.vue'
import TableContainer from '../components/TableContainer.vue'

const { t } = useTranslation()
const appStore = useAppConfigStore()
const userStore = useUserStore()
const { appInfo } = storeToRefs(appStore)
const consultRef = ref<InstanceType<typeof Auth.Consult> | null>(null)
const routerViewKey = ref(0)

/** 将导出 JSON 中的旧 snowflake ID 批量替换为新 ID（避免先写流程后导模块导致引用断裂） */
function applyIdMapping(jsonStr: string, idMapping: Record<string, string>) {
  const entries = Object.entries(idMapping).filter(([a, b]) => a && b && a !== b)
  entries.sort((x, y) => y[0].length - x[0].length)
  let s = jsonStr
  for (const [oldId, newId] of entries)
    s = s.split(oldId).join(newId)

  return s
}

async function checkProjectLimit() {
  if (userStore.currentTenant?.tenantType !== 'enterprise') {
    const res = await checkProjectNum()
    if (!res.data) {
      consultRef.value?.init({
        authType: appInfo.value.appAuthType,
        trigger: 'modal',
        modalConfirm: {
          title: t('designerManage.limitReachedTitle'),
          content: userStore.currentTenant?.tenantType === 'personal'
            ? t('designerManage.personalLimitReachedContent')
            : t('designerManage.proLimitReachedContent'),
          okText: userStore.currentTenant?.tenantType === 'personal'
            ? t('designerManage.upgradeToPro')
            : t('designerManage.upgradeToEnterprise'),
          cancelText: t('designerManage.gotIt'),
        },
        consult: {
          consultTitle: t('designerManage.consult'),
          consultEdition: userStore.currentTenant?.tenantType === 'personal' ? 'professional' : 'enterprise',
          consultType: 'consult',
        },
      })
      return false
    }
  }
  return true
}

async function createRobot() {
  if (!await checkProjectLimit())
    return

  newProjectModal.show({
    title: t('newProject'),
    name: t('projectName'),
    defaultName: getDefaultName,
    onConfirm: (name: string) => newProject(name),
  })

  const newProject = async (projectName: string) => {
    try {
      const res = await createProject({ name: projectName })
      const projectId = res.data.robotId

      useRoutePush({ name: ARRANGE, query: { projectId, projectName } })
      message.success(t('createSuccess'))
    }
    finally {
      newProjectModal.hide()
    }
  }
}

async function importRobot() {
  if (!await checkProjectLimit())
    return

  importProjectModal.show({
    title: t('importRPAApplication'),
    name: t('projectName'),
    onConfirm: (name: string, importData: AnyObj) => doImportProject(name, importData),
  })
}

async function doImportProject(projectName: string, importData: AnyObj) {
  try {
    const res = await createProject({ name: projectName })
    const newRobotId = res.data.robotId

    const idMapping: Record<string, string> = {}

    const existingModules = await getProcessAndCodeList({ robotId: newRobotId })
    const existingMainProcess = existingModules.find((m: AnyObj) => m.name === '主流程' && m.resourceCategory === 'process')

    // 先分配全部流程 ID（与后端 copy 时先 processCopy、再按映射替换子流程/模块引用一致）
    if (importData.processes?.length) {
      for (const process of importData.processes) {
        const isMainProcess = process.processName === '主流程'

        if (isMainProcess && existingMainProcess) {
          idMapping[process.processId] = existingMainProcess.resourceId
        }
        else {
          const uniqueName = await genProcessName({ robotId: newRobotId })
          const newProcessId = await addProcess({ robotId: newRobotId, processName: uniqueName })
          idMapping[process.processId] = newProcessId

          try {
            await renameProcess({ robotId: newRobotId, processId: newProcessId, processName: process.processName })
          }
          catch {
            // 如果重命名失败，保留生成的唯一名称
          }
        }
      }
    }

    // 再导入 Python 模块并写入 moduleId 映射（流程画布中模块引用必须在保存流程前进入 idMapping）
    if (importData.modules?.length) {
      for (const module of importData.modules) {
        const uniqueName = await genProcessPyCodeName({ robotId: newRobotId })
        const newModuleId = await addProcessPyCode({ robotId: newRobotId, moduleName: uniqueName })
        idMapping[module.moduleId] = newModuleId

        try {
          await renameProcessPyCode({ robotId: newRobotId, moduleId: newModuleId, moduleName: module.moduleName })
        }
        catch {
        }

        if (module.moduleContent) {
          await saveProcessPyCode({ robotId: newRobotId, moduleId: newModuleId, moduleContent: module.moduleContent })
        }
      }
    }

    // 智能组件（exportFormatVersion>=2 或旧包无此字段则跳过）
    if (importData.smartComponents?.length) {
      for (const sc of importData.smartComponents) {
        const newSmartId = await saveSmartComp({
          robotId: newRobotId,
          smartId: '',
          smartType: sc.smartType,
          detail: sc.detail,
        })
        idMapping[sc.smartId] = newSmartId
      }
    }

    // 最后一次性写入流程 JSON（替换 process / module / smart 等全部 ID）
    if (importData.processes?.length) {
      for (const process of importData.processes) {
        const newProcessId = idMapping[process.processId]
        if (!newProcessId)
          continue

        const processJson = applyIdMapping(JSON.stringify(process.processJson ?? []), idMapping)
        await flowSave({ robotId: newRobotId, processId: newProcessId, processJson })
      }
    }

    if (importData.globalVariables?.length) {
      for (const globalVar of importData.globalVariables) {
        const { globalId, ...varData } = globalVar
        await addGlobalVariable({ ...varData, robotId: newRobotId })
      }
    }

    if (importData.configParams?.length) {
      for (const configParam of importData.configParams) {
        const { id, ...paramData } = configParam
        const remapped: AnyObj = { ...paramData, robotId: newRobotId }
        if (remapped.processId && idMapping[remapped.processId])
          remapped.processId = idMapping[remapped.processId]
        if (remapped.moduleId && idMapping[remapped.moduleId])
          remapped.moduleId = idMapping[remapped.moduleId]

        await createConfigParam(remapped)
      }
    }

    if (importData.elements?.length) {
      for (const group of importData.elements) {
        await addElementGroup({ robotId: newRobotId, elementType: 'common', groupName: group.name })

        if (group.elements?.length) {
          for (const element of group.elements) {
            const { id, groupId, ...rest } = element
            await addElement({
              type: 'common',
              robotId: newRobotId,
              groupName: group.name,
              element: {
                ...rest,
                commonSubType: rest.commonSubType || 'single',
              },
            })
          }
        }
      }
    }

    if (importData.cvElements?.length) {
      for (const group of importData.cvElements) {
        await addElementGroup({ robotId: newRobotId, elementType: 'cv', groupName: group.name })

        if (group.elements?.length) {
          for (const element of group.elements) {
            const { id, groupId, ...rest } = element
            await addElement({
              type: 'cv',
              robotId: newRobotId,
              groupName: group.name,
              element: {
                ...rest,
              },
            })
          }
        }
      }
    }

    if (importData.packages?.length) {
      const existingPackages = await getPyPackageListApi({ robotId: newRobotId })
      const existingNames = new Set((existingPackages.data || []).map((p: AnyObj) => p.packageName))

      for (const pkg of importData.packages) {
        if (!existingNames.has(pkg.packageName)) {
          await addPyPackageApi({ robotId: newRobotId, packageName: pkg.packageName, packageVersion: pkg.packageVersion, mirror: pkg.mirror || '' })
        }
      }
    }

    if (importData.componentUses?.length) {
      for (const cu of importData.componentUses) {
        try {
          await addComponentUse({ componentId: cu.componentId, robotId: newRobotId })
        }
        catch {
          // 已引用等
        }
      }
    }

    if (importData.blockedComponentIds?.length) {
      for (const cid of importData.blockedComponentIds) {
        try {
          await removeComponent({ robotId: newRobotId, componentId: cid })
        }
        catch {
        }
      }
    }

    routerViewKey.value++
    message.success(t('common.importSuccess'))
  }
  catch (error) {
    message.error(t('common.importFailed'))
    throw error
  }
  finally {
    importProjectModal.hide()
  }
}

function handleActionClick(key: string) {
  if (key === 'import') {
    importRobot()
  }
}
</script>

<template>
  <div class="h-full flex flex-col z-10 relative">
    <Banner
      :title="$t('designerManage.oneClickAutomation')"
      :sub-title="$t('designerManage.freeFromRepetition')"
      :action-text="$t('designerManage.createRobot')"
      :actions="[{ text: $t('importRPAApplication'), key: 'import' }]"
      @action="createRobot"
      @action-click="handleActionClick"
    />
    <TableContainer>
      <router-view :key="routerViewKey" />
    </TableContainer>
    <Auth.Consult ref="consultRef" trigger="modal" :auth-type="appInfo.appAuthType" />
  </div>
</template>
