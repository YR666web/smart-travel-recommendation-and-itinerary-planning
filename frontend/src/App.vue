<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="logo">智能旅行推荐与行程规划</div>
      <el-button text @click="keyDialog = true">API Key</el-button>
      <el-menu mode="horizontal" :default-active="$route.path" router class="menu">
        <el-menu-item index="/chat">智能问答</el-menu-item>
        <el-menu-item index="/planner">智能行程</el-menu-item>
        <el-menu-item index="/attractions">景点检索</el-menu-item>
        <el-menu-item index="/routes">线路检索</el-menu-item>
        <el-menu-item index="/info">实用信息</el-menu-item>
        <el-menu-item index="/admin/import">内容导入</el-menu-item>
        <el-menu-item index="/admin/documents">元数据管理</el-menu-item>
      </el-menu>
    </el-header>
    <el-dialog v-model="keyDialog" title="访问密钥" width="400px">
      <el-input v-model="apiKey" type="password" show-password placeholder="未启用鉴权时可留空" />
      <template #footer><el-button type="primary" @click="saveKey">保存</el-button></template>
    </el-dialog>
    <el-main class="main">
      <router-view v-slot="{ Component }">
        <keep-alive>
          <component :is="Component" />
        </keep-alive>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'

const keyDialog = ref(false)
const apiKey = ref(sessionStorage.getItem('jingwen_api_key') || '')
function saveKey() {
  if (apiKey.value) sessionStorage.setItem('jingwen_api_key', apiKey.value)
  else sessionStorage.removeItem('jingwen_api_key')
  keyDialog.value = false
}
</script>

<style>
* {
  box-sizing: border-box;
}
body {
  margin: 0;
}
.layout {
  height: 100vh;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.header {
  height: 60px;
  min-width: 0;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
  padding: 0 20px;
}
.logo {
  flex-shrink: 0;
  white-space: nowrap;
  font-weight: 700;
  font-size: 18px;
  margin-right: 40px;
  color: #409eff;
}
.menu {
  flex: 1;
  min-width: 0;
  border-bottom: none;
}
.header > .el-button { flex-shrink: 0; }
.main {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  padding: 16px;
}
.main > * {
  height: 100%;
  overflow: auto;
}
</style>
