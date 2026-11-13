<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import type {Comparison} from '../types/domain';
import {getComparison} from '../api/segments';
import type {Run} from '../types/domain';
import {number,percent} from '../utils/format';

const props=defineProps<{runs:Run[];initialA?:number}>();
const selectedA=ref(props.initialA||0);
const selectedB=ref(0);
const result=ref<Comparison|null>(null);
const loading=ref(false);
const error=ref('');

const completed=computed(()=>props.runs.filter(r=>r.status==='completed'));
const canCompare=computed(()=>!!selectedA.value&&!!selectedB.value&&selectedA.value!==selectedB.value);

watch(completed,()=>{
 if(!completed.value.some(r=>r.id===selectedA.value))selectedA.value=completed.value[0]?.id||0;
 if(!completed.value.some(r=>r.id===selectedB.value))selectedB.value=completed.value.find(r=>r.id!==selectedA.value)?.id||0;
},{immediate:true});
watch(()=>props.initialA,value=>{if(value&&completed.value.some(r=>r.id===value)){selectedA.value=value;result.value=null;}});

async function compare(){
 if(!canCompare.value)return;
 loading.value=true;error.value='';
 try{result.value=await getComparison(selectedA.value,selectedB.value);}
 catch(e){result.value=null;error.value=e instanceof Error?e.message:String(e);}
 finally{loading.value=false;}
}

function swap(){const a=selectedA.value;selectedA.value=selectedB.value;selectedB.value=a;result.value=null;}
function clear(){result.value=null;}
</script>

<template>
<section class="comparison">
 <div class="section-title">
  <h2>两期迁移对比 <small>按匿名客户编号对齐，群号变化不等于流失</small></h2>
 </div>
 <div class="comparison-picker">
  <label>A 期实验<select v-model="selectedA" @change="clear"><option v-for="r in completed" :key="r.id" :value="r.id">#{{r.id}} {{r.name}} · {{r.result.sample_count||'—'}} 位</option></select></label>
  <button class="outline swap" :disabled="!canCompare" aria-label="交换两期" @click="swap">A ⇄ B</button>
  <label>B 期实验<select v-model="selectedB" @change="clear"><option v-for="r in completed" :key="r.id" :value="r.id">#{{r.id}} {{r.name}} · {{r.result.sample_count||'—'}} 位</option></select></label>
  <button class="primary" :disabled="!canCompare||loading" @click="compare">{{loading?'正在比对…':'计算迁移 →'}}</button>
 </div>

  <p v-if="completed.length<2" class="muted">至少需要两个已完成实验才能对比。待计算或失败的实验不会出现在此列表。</p>
 <p v-else-if="selectedA===selectedB" class="muted">A、B 两期需要选择不同实验。</p>
 <ErrorNotice :message="error" @retry="compare"/>
 <p v-if="!result&&!error&&completed.length>=2&&canCompare" class="muted">选择两期后点击“计算迁移”，结果只读展示，不会修改实验、群组或已批准名单。</p>

 <template v-if="result">
  <div class="comparison-heads">
   <div>
    <p class="eyebrow">A 期 / 基准实验</p>
    <h3>{{result.run_a.name}}</h3>
    <p class="muted">#{{result.run_a.id}} · {{result.run_a.dataset_name}} · {{number(result.run_a.total)}} 位 · {{result.run_a.group_count}} 群</p>
   </div>
   <div>
    <p class="eyebrow">B 期 / 对照实验</p>
    <h3>{{result.run_b.name}}</h3>
    <p class="muted">#{{result.run_b.id}} · {{result.run_b.dataset_name}} · {{number(result.run_b.total)}} 位 · {{result.run_b.group_count}} 群</p>
   </div>
  </div>

  <div v-if="!result.comparable" class="comparison-incomparable">
   <h3>不可比较：两期没有共同的匿名客户</h3>
   <p>{{result.reason}}</p>
   <p class="muted">A 期 {{number(result.run_a.total)}} 位、B 期 {{number(result.run_b.total)}} 位，但匿名编号集合没有交集。群号或群组名称无法在本页面建立对应关系。</p>
  </div>

  <template v-else>
   <div class="migration-stats">
    <div><strong>{{number(result.summary.migrated)}}</strong><span>迁移客户</span><small>两期处于不同群组</small></div>
    <div><strong>{{percent(result.summary.migration_share_of_common)}}</strong><span>迁移率 / 共同客户</span><small>{{number(result.summary.common)}} 位共同客户</small></div>
    <div><strong>{{number(result.summary.added)}}</strong><span>B 期新增</span><small>A 期没有的编号</small></div>
    <div><strong>{{number(result.summary.left)}}</strong><span>B 期离开</span><small>B 期没有的 A 期编号</small></div>
    <div><strong>{{number(result.summary.retained)}}</strong><span>留在对应群组</span><small>未发生组间迁移</small></div>
   </div>

   <div class="reconcile">
    <p class="eyebrow">RECONCILIATION / 两期总人数对账</p>
    <div class="reconcile-rows">
     <div><span>A 期 {{number(result.run_a.total)}}</span><b>=</b><span>{{number(result.summary.retained)}} 留在对应群 + {{number(result.summary.migrated)}} 迁移 + {{number(result.summary.left)}} 离开</span><i :class="{ok:result.summary.reconciled}">{{result.summary.reconciled?'✓ 对账一致':'✗ 需复核'}}</i></div>
     <div><span>B 期 {{number(result.run_b.total)}}</span><b>=</b><span>{{number(result.summary.retained)}} 留在对应群 + {{number(result.summary.migrated)}} 迁移 + {{number(result.summary.added)}} 新增</span><i :class="{ok:result.summary.reconciled}">{{result.summary.reconciled?'✓ 对账一致':'✗ 需复核'}}</i></div>
    </div>
    <p class="muted">迁移按共同编号实际所在群组计算；新增和离开按编号集合差计算。两期数据集不同也可比较，只要编号可对齐。</p>
   </div>

   <div class="section-title"><h2>群组对应 <small>按共同客户最大重叠自动匹配</small></h2></div>
   <div class="table-wrap">
    <table>
     <thead><tr><th>A 期群组</th><th>B 期群组</th><th>共同客户</th><th>占 A 群</th><th>编号</th><th>名称</th></tr></thead>
     <tbody>
      <tr v-for="(m,i) in result.matches" :key="i">
       <td><strong>{{m.a_label===null?'—':'A'+m.a_label+' · '+m.a_name}}</strong><small>{{m.a_size===null?'':'A 期 '+m.a_size+' 位'}}</small></td>
       <td><strong>{{m.b_label===null?'—':'B'+m.b_label+' · '+m.b_name}}</strong><small>{{m.b_size===null?'':'B 期 '+m.b_size+' 位'}}</small></td>
       <td>{{number(m.overlap)}}</td>
       <td>{{m.a_label===null?'—':percent(m.share_of_a_group)}}</td>
       <td><span v-if="m.label_changed" class="flag">编号变化</span><span v-else-if="m.a_label!==null&&m.b_label!==null" class="quiet">不变</span><span v-else class="quiet">无对应</span></td>
       <td><span v-if="m.name_changed" class="flag">名称变化</span><span v-else-if="m.a_label!==null&&m.b_label!==null" class="quiet">不变</span><span v-else class="quiet">—</span></td>
      </tr>
     </tbody>
    </table>
   </div>

   <div class="section-title"><h2>迁移去向 <small>离开对应群组的共同客户</small></h2></div>
   <div v-if="result.migrations.length" class="table-wrap">
    <table>
     <thead><tr><th>从 A 期</th><th>到 B 期</th><th>人数</th><th>占共同客户</th><th>占 A 群</th></tr></thead>
     <tbody>
      <tr v-for="(m,i) in result.migrations" :key="i">
       <td><strong>A{{m.a_label}} · {{m.a_name}}</strong></td>
       <td><strong>B{{m.b_label}} · {{m.b_name}}</strong></td>
       <td>{{number(m.count)}}</td>
       <td>{{percent(m.share_of_common)}}</td>
       <td>{{percent(m.share_of_a_group)}}</td>
      </tr>
     </tbody>
    </table>
   </div>
   <p v-else class="muted">没有共同客户在群组之间迁移；{{number(result.summary.retained)}} 位共同客户都留在对应群组。</p>

   <div class="section-title"><h2>迁移矩阵 <small>行 = A 期群组，列 = B 期群组；高亮为对应关系</small></h2></div>
   <div class="table-wrap">
    <table class="matrix">
     <thead><tr><th>A 期 ＼ B 期</th><th v-for="b in result.matrix[0]?.cells||[]" :key="b.b_label">B{{b.b_label}}<small>{{b.b_name}}</small></th></tr></thead>
     <tbody>
      <tr v-for="row in result.matrix" :key="row.a_label">
       <td><strong>A{{row.a_label}} · {{row.a_name}}</strong><small>{{row.a_size}} 位</small></td>
       <td v-for="cell in row.cells" :key="cell.b_label" :class="{matched:cell.matched,zero:!cell.count}">
        <strong>{{number(cell.count)}}</strong>
        <small v-if="cell.count">{{percent(cell.share_of_a_group)}} / A群</small>
       </td>
      </tr>
     </tbody>
    </table>
   </div>

   <div class="code-lists">
    <div>
     <p class="eyebrow">ADDED / B 期新增 {{number(result.summary.added)}} 位</p>
     <p v-if="!result.added_codes.length" class="muted">无</p>
     <code v-for="c in result.added_codes" :key="c">{{c}}</code>
    </div>
    <div>
     <p class="eyebrow">LEFT / B 期离开 {{number(result.summary.left)}} 位</p>
     <p v-if="!result.left_codes.length" class="muted">无</p>
     <code v-for="c in result.left_codes" :key="c">{{c}}</code>
    </div>
   </div>

   <ul class="comparison-notes"><li v-for="(n,i) in result.notes" :key="i">{{n}}</li></ul>
  </template>
 </template>
</section>
</template>
