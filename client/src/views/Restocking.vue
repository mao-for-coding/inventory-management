<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ formatCurrency(totalCost, currentCurrency) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatCurrency(remainingBudget, currentCurrency) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="budget-slider-header">
          <span class="budget-slider-label">{{ t('restocking.budgetLabel') }}</span>
          <span class="budget-slider-value">{{ formatCurrency(budget, currentCurrency) }}</span>
        </div>
        <input
          type="range"
          class="budget-slider"
          min="0"
          :max="sliderMax"
          step="500"
          v-model.number="budget"
        >
      </div>

      <div v-if="orderError" class="error">{{ orderError }}</div>
      <div v-if="placedOrder" class="success-banner">
        {{ t('restocking.orderPlaced', { number: placedOrder.order_number, date: formatDate(placedOrder.expected_delivery) }) }}
        <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
          <button
            class="place-order-btn"
            :disabled="placing || !recommendations.length || placedOrder"
            @click="placeOrder"
          >
            {{ placing ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.runningTotal') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in recommendations" :key="row.sku">
                <td>{{ translateProductName(row.name) }}</td>
                <td><strong>{{ row.sku }}</strong></td>
                <td>{{ row.qty }}</td>
                <td>{{ formatCurrency(row.unitCost, currentCurrency) }}</td>
                <td>{{ formatCurrency(row.lineTotal, currentCurrency) }}</td>
                <td>{{ formatCurrency(row.runningTotal, currentCurrency) }}</td>
              </tr>
              <tr v-if="!recommendations.length">
                <td colspan="6">{{ t('restocking.noRecommendations') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="skippedCount > 0" class="skipped-note">
          {{ t('restocking.skippedForecasts', { count: skippedCount }) }}
        </p>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency.js'

export default {
  name: 'Restocking',
  setup() {
    const { t, translateProductName, currentCurrency, currentLocale } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const inventory = ref([])

    const budget = ref(0)
    let budgetInitialized = false

    const placing = ref(false)
    const placedOrder = ref(null)
    const orderError = ref(null)

    const inventoryMap = computed(() => {
      const map = new Map()
      inventory.value.forEach(item => map.set(item.sku, item))
      return map
    })

    // All forecasts with a positive demand gap
    const positiveGapForecasts = computed(() => {
      return forecasts.value.filter(f => f.forecasted_demand > f.current_demand)
    })

    const candidates = computed(() => {
      return positiveGapForecasts.value
        .filter(f => inventoryMap.value.has(f.item_sku))
        .map(f => {
          const item = inventoryMap.value.get(f.item_sku)
          const qty = f.forecasted_demand - f.current_demand
          const unitCost = item.unit_cost
          const lineTotal = +(qty * unitCost).toFixed(2)
          return {
            sku: f.item_sku,
            name: item.name,
            qty,
            unitCost,
            lineTotal
          }
        })
        .sort((a, b) => b.qty - a.qty)
    })

    const sliderMax = computed(() => {
      const total = candidates.value.reduce((sum, c) => sum + c.lineTotal, 0)
      return Math.ceil(total / 1000) * 1000
    })

    const skippedCount = computed(() => {
      return positiveGapForecasts.value.filter(f => !inventoryMap.value.has(f.item_sku)).length
    })

    const recommendations = computed(() => {
      const result = []
      let spent = 0
      for (const candidate of candidates.value) {
        if (spent + candidate.lineTotal <= budget.value) {
          spent += candidate.lineTotal
          result.push({ ...candidate, runningTotal: +spent.toFixed(2) })
        }
      }
      return result
    })

    const totalCost = computed(() => {
      return recommendations.value.reduce((sum, r) => sum + r.lineTotal, 0)
    })

    const remainingBudget = computed(() => {
      return Math.max(0, budget.value - totalCost.value)
    })

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory({})
        ])
        forecasts.value = forecastsData
        inventory.value = inventoryData

        if (!budgetInitialized) {
          budget.value = Math.round(sliderMax.value / 2 / 500) * 500
          budgetInitialized = true
        }
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    }

    watch(budget, () => {
      placedOrder.value = null
      orderError.value = null
    })

    const placeOrder = async () => {
      if (placing.value || !recommendations.value.length || placedOrder.value) return
      placing.value = true
      orderError.value = null
      try {
        const order = await api.createOrder({
          items: recommendations.value.map(r => ({ sku: r.sku, quantity: r.qty }))
        })
        placedOrder.value = order
      } catch (err) {
        orderError.value = t('restocking.orderFailed')
        console.error(err)
      } finally {
        placing.value = false
      }
    }

    const formatDate = (dateString) => {
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return new Date(dateString).toLocaleDateString(locale, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    onMounted(loadData)

    return {
      t,
      translateProductName,
      currentCurrency,
      formatCurrency,
      loading,
      error,
      budget,
      sliderMax,
      recommendations,
      skippedCount,
      totalCost,
      remainingBudget,
      placing,
      placedOrder,
      orderError,
      placeOrder,
      formatDate
    }
  }
}
</script>

<style scoped>
.budget-slider-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-slider-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-slider-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  outline: none;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 2px solid #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: 2px solid #ffffff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
}

.place-order-btn {
  background: #2563eb;
  color: #ffffff;
  border: none;
  padding: 0.625rem 1.25rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-banner {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.success-banner a {
  color: #166534;
  font-weight: 600;
  text-decoration: underline;
  white-space: nowrap;
}

.skipped-note {
  margin-top: 0.75rem;
  font-size: 0.813rem;
  color: #64748b;
  font-style: italic;
}
</style>
