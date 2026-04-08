<script setup lang="ts">
import { Auth } from '@rpa/components/auth'
import { message } from 'ant-design-vue'
import { useTranslation } from 'i18next-vue'
import { storeToRefs } from 'pinia'
import { ref } from 'vue'

import { createConfigParam } from '@/api/atom'
import { checkProjectNum, createProject, getDefaultName } from '@/api/project'
import { addElement, addElementGroup, addGlobalVariable, addProcess, addProcessPyCode, addPyPackageApi, flowSave, genProcessName, genProcessPyCodeName, getProcessAndCodeList, getPyPackageListApi, renameProcess, renameProcessPyCode, saveProcessPyCode } from '@/api/resource'
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

    if (importData.processes?.length) {
      for (const process of importData.processes) {
        const isMainProcess = process.processName === '主流程'

        if (isMainProcess && existingMainProcess) {
          idMapping[process.processId] = existingMainProcess.resourceId

          let processJson = JSON.stringify(process.processJson)
          for (const [oldId, newId] of Object.entries(idMapping)) {
            processJson = processJson.replaceAll(oldId, newId)
          }

          await flowSave({ robotId: newRobotId, processId: existingMainProcess.resourceId, processJson })
        } else {
          const uniqueName = await genProcessName({ robotId: newRobotId })
          const newProcessId = await addProcess({ robotId: newRobotId, processName: uniqueName })
          idMapping[process.processId] = newProcessId

          try {
            await renameProcess({ robotId: newRobotId, processId: newProcessId, processName: process.processName })
          } catch {
            // 如果重命名失败，保留生成的唯一名称
          }

          let processJson = JSON.stringify(process.processJson)
          for (const [oldId, newId] of Object.entries(idMapping)) {
            processJson = processJson.replaceAll(oldId, newId)
          }

          await flowSave({ robotId: newRobotId, processId: newProcessId, processJson })
        }
      }
    }

    if (importData.modules?.length) {
      for (const module of importData.modules) {
        const uniqueName = await genProcessPyCodeName({ robotId: newRobotId })
        const newModuleId = await addProcessPyCode({ robotId: newRobotId, moduleName: uniqueName })
        idMapping[module.moduleId] = newModuleId

        try {
          await renameProcessPyCode({ robotId: newRobotId, moduleId: newModuleId, moduleName: module.moduleName })
        } catch {
          // 如果重命名失败，保留生成的唯一名称
        }

        if (module.moduleContent) {
          await saveProcessPyCode({ robotId: newRobotId, moduleId: newModuleId, moduleContent: module.moduleContent })
        }
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
        await createConfigParam({ ...paramData, robotId: newRobotId })
      }
    }

    if (importData.elements?.length) {
      for (const group of importData.elements) {
        const groupRes = await addElementGroup({ robotId: newRobotId, elementType: 'common', groupName: group.name })
        const newGroupId = groupRes.data

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
        const groupRes = await addElementGroup({ robotId: newRobotId, elementType: 'cv', groupName: group.name })
        const newGroupId = groupRes.data

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
