export const reconcileViewTemplate = `
<section class="panel">
  <h2>仓间对账互证</h2>
  <p class="hint">配额在批差额之外单列拆轨一致：影子封批与解冻待提交都计入异态。</p>
  <div class="form-row">
    <div><label>仓间编码</label><input v-model="reconCode"/></div>
    <div><label>批次互证编码</label><input v-model="proofCode"/></div>
  </div>
  <div class="actions">
    <button @click="loadRecon">对账单仓</button>
    <button class="secondary" @click="loadProof">批次互证</button>
    <button class="secondary" @click="loadReconAll">全仓对账</button>
  </div>
  <div v-if="reconOne" class="detail-box">
    <p>配额 {{ reconOne.quota_batches }} · 在批 {{ reconOne.active_batches }} · 正式封批 {{ reconOne.sealed_batches }} · 影子 {{ reconOne.shadow_sealed_batches }} · 解冻待提交 {{ reconOne.thaw_pending_batches }} · <span :class="reconOne.balanced ? 'ok' : 'bad'">{{ reconOne.balanced ? "平衡" : "失衡" }}</span></p>
  </div>
  <div v-if="proofOne" class="detail-box">
    <p>状态 {{ proofOne.status }} · 正式封批 {{ proofOne.official_seal ? "是" : "否" }} · 影子封批 {{ proofOne.shadow_sealed ? "是" : "否" }} · 解冻待提交 {{ proofOne.thaw_pending }} · 开放游标 {{ proofOne.open_excursions }} · 温谱 {{ proofOne.spectrum_exports }} · <span :class="proofOne.consistent ? 'ok' : 'bad'">{{ proofOne.consistent ? "两轨一致" : "两轨异态" }}</span></p>
  </div>
  <table class="data-table">
    <thead><tr><th>仓间</th><th>区域</th><th>在批</th><th>正式封批</th><th>影子</th><th>解冻待提交</th><th>余配额</th><th>平衡</th></tr></thead>
    <tbody>
      <tr v-for="r in reconAllItems" :key="r.chamber_code">
        <td>{{ r.chamber_code }}</td>
        <td>{{ r.region }}</td>
        <td>{{ r.active_batches }}</td>
        <td>{{ r.sealed_batches }}</td>
        <td>{{ r.shadow_sealed_batches }}</td>
        <td>{{ r.thaw_pending_batches }}</td>
        <td>{{ r.quota_left }}</td>
        <td>{{ r.balanced ? "是" : "否" }}</td>
      </tr>
    </tbody>
  </table>
</section>
`;