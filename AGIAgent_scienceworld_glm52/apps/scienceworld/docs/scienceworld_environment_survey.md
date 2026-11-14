# ScienceWorld 环境全面调查

> 基于 `scienceworld` 包（v1.2.3，Scala 实现 + Python `py4j` 封装）以及本仓库 `apps/scienceworld/` 中的使用代码整理而成。
> 调查时间：2026-06-17

---

## 1. 环境整体架构

ScienceWorld 是一个基于物理/化学/生物规则的文本交互式沙盒环境。核心逻辑用 Scala 实现，编译为 `scienceworld.jar`，通过 `py4j` 暴露给 Python。

```
┌─────────────────────────────────────────────────────────────┐
│  Python API: scienceworld.scienceworld.ScienceWorldEnv       │
│  (加载 JAR、调用 JVM、管理 session)                          │
├─────────────────────────────────────────────────────────────┤
│  JVM / Scala 模拟器 (scienceworld.jar)                        │
│  - 对象树 (EnvObject)                                        │
│  - 动作解析与执行 (ActionHandler)                            │
│  - 物理/化学/生物 tick (热传导、物态变化、燃烧、电路、生命)  │
│  - 任务目标判定 (GoalSequence)                               │
└─────────────────────────────────────────────────────────────┘
```

本仓库中的封装层：

| 文件 | 作用 |
|------|------|
| `src/tools/scienceworld_tools.py` | 向 agent 暴露 `scienceworld_action` 原生工具 |
| `apps/scienceworld/run_all_tasks.py` | benchmark 切片、phase1/phase2 执行、结果汇总 |
| `apps/scienceworld/world_understanding_evaluator.py` | 将 agent 世界模型与 `env.getObjectTree()` 做对比 |

---

## 2. 世界结构：位置（Locations）

世界对象树根节点是 `Universe`，下一层是若干个 `Room` 或 `Outside`。位置本身也是容器（`IsOpenUnclosableContainer`），默认开放且不可关闭。

### 2.1 标准房屋布局

从 `BuildingMaker.scala` 中可看到默认会创建以下房间：

| 位置 | 类型 | 备注 |
|------|------|------|
| kitchen | Room | 有 stove、oven、sink、fridge、freezer、counter、cupboard 等 |
| living room | Room | 有 couch、picture 等 |
| bedroom | Room | 有 bed、closet 等 |
| bathroom | Room | 有 bathtub、toilet、sink 等 |
| workshop | Room | 有工作台、工具等 |
| greenhouse | Room | 有植物、花、花盆等 |
| art studio | Room | 有颜料、画等 |
| hallway | Room | 连接多个房间的中枢 |
| outside | Outside | 户外，有 ground、air、fire pit、fountain 等 |
| foundry | Room | 铸造间，有 blast furnace 等高温设备 |
| sewer | 特殊容器 | 与 bathroom 等相连，可排水 |

### 2.2 连接方式

房间之间通过 `Door`（`Portal` 子类）连接。门的状态包括：

- `isOpen`：是否打开
- `isOpenable`：是否可打开/关闭
- `isLocked` / `isLockable`：是否上锁/可上锁

示例连接（来自源码）：

```scala
mkDoor(roomKitchen, roomHallway)
mkDoor(roomLivingRoom, roomHallway)
mkDoor(roomBedroom, roomHallway)
mkDoor(roomBathroom, roomKitchen)
mkDoor(roomWorkshop, roomHallway)
mkDoor(roomGreenhouse, roomHallway)
mkDoor(roomArtStudio, roomHallway)
mkDoor(roomKitchen, outside)
mkDoor(roomGreenhouse, outside)
mkDoor(foundry, outside)
```

### 2.3 运行时观察到的位置

通过 `get_possible_objects()` 与 `getObjectTree()` 在不同任务中观察到：

```
art studio, bathroom, bedroom, foundry, greenhouse, hallway,
kitchen, living room, outside, sewer, workshop
```

---

## 3. 物体（Objects）与分类

### 3.1 物体类型总数

`object_type_ids.tsv` 中定义了 **218 个物体类**，每个类对应一个整数 `typeID`。下面按包路径分组。

#### Agent 与库存

| 类名 | typeID |
|------|--------|
| Agent | 0 |
| InventoryContainer | 1 |

#### 容器（containers）

| 类名 | typeID |
|------|--------|
| BookShelf | 2 |
| CeramicCup | 3 |
| Container | 4 |
| Cup | 5 |
| FlowerPot | 6 |
| GlassCup | 7 |
| GlassJar | 8 |
| Jug | 9 |
| MetalPot | 10 |
| PaperCup | 11 |
| PlasticCup | 12 |
| SelfWateringFlowerPot | 13 |
| Sewer | 14 |
| TinCup | 15 |
| WoodBowl | 16 |
| WoodCup | 17 |

#### 家具类容器（furniture）

| 类名 | typeID |
|------|--------|
| Bed | 18 |
| BeeHive | 19 |
| Chair | 20 |
| Closet | 21 |
| Couch | 22 |
| Counter | 23 |
| Cupboard | 24 |
| Desk | 25 |
| Drawer | 26 |
| Mattress | 27 |
| Pillow | 28 |
| Sittable | 29 |
| SteelTable | 30 |
| WoodTable | 31 |

#### 设备（devices）

| 类名 | typeID | 说明 |
|------|--------|------|
| Axe | 32 | 工具 |
| Bathtub | 33 | 容器/排水 |
| BlastFurnace | 34 | 高温热源（最高 3000°C） |
| CoolingSource | 35 | 制冷源抽象类 |
| Device | 36 | 设备抽象类 |
| Freezer | 37 | 冷冻（-18°C） |
| Fridge | 38 | 冷藏 |
| HeatSource | 39 | 热源抽象类 |
| HotPlate | 40 | 加热板 |
| Lighter | 41 | 点火器 |
| Oven | 42 | 烤箱（最高 540°C） |
| Shovel | 43 | 工具 |
| Sink | 44 | 水槽 |
| StopWatch | 45 | 秒表 |
| Stove | 46 | 炉灶 |
| Thermometer | 47 | 温度计 |
| Toilet | 48 | 马桶 |
| UltraColdFreezer | 49 | 超低温冰箱（-86°C） |

#### 文档（document）

| 类名 | typeID |
|------|--------|
| Book | 50 |
| BookBeowulf | 51 |
| BookFrankenstein | 52 |
| BookMobyDick | 53 |
| BookOriginOfSpecies | 54 |
| BookPrideAndPrejudice | 55 |
| BookSherlockHolmes | 56 |
| ColoredPaper | 57 |
| Document | 58 |
| Paper | 59 |
| Recipe | 60 |

#### 电气元件（electricalcomponent）

| 类名 | typeID |
|------|--------|
| Anode | 61 |
| Battery | 62 |
| Cathode | 63 |
| ElectricBuzzer | 64 |
| ElectricMotor | 65 |
| ElectricalComponent | 66 |
| GasGenerator | 67 |
| Generator | 68 |
| LightBulb | 69 |
| NuclearGenerator | 70 |
| PolarizedElectricalComponent | 71 |
| RenewableOutdoorGenerator | 72 |
| SolarPanel | 73 |
| Switch | 74 |
| Terminal | 75 |
| UnpolarizedElectricalComponent | 76 |
| WindGenerator | 77 |
| Wire | 78 |

#### 户外环境（environmentoutside）

| 类名 | typeID |
|------|--------|
| FirePit | 79 |
| Fountain | 80 |
| Ground | 81 |
| Hole | 82 |

#### 生物（livingthing）

| 类名 | typeID | 类名 | typeID |
|------|--------|------|--------|
| LivingThing | 83 | Animal | 84 |
| Ant | 85 | Beaver | 86 |
| Bee | 87 | BlueJay | 88 |
| BrownBear | 89 | Butterfly | 90 |
| Chameleon | 91 | Chipmunk | 92 |
| Crocodile | 93 | Dove | 94 |
| Dragonfly | 95 | Elephant | 96 |
| Frog | 97 | GiantTortoise | 98 |
| Hedgehog | 99 | Moth | 100 |
| Mouse | 101 | Parrot | 102 |
| Rabbit | 103 | Toad | 104 |
| Turtle | 105 | WanderingAnimal | 106 |
| Wolf | 107 | AppleTree | 108 |
| ApricotTree | 109 | AvocadoTree | 110 |
| BananaTree | 111 | CherryTree | 112 |
| Flower | 113 | FruitingTree | 114 |
| GrapefruitTree | 115 | LemonTree | 116 |
| OrangeTree | 117 | PeaPlant | 118 |
| PeachTree | 119 | PearTree | 120 |
| Plant | 121 | Pollen | 122 |
| RandomGeneticsPlants | 123 | RandomGeneticsPlantsB | 124 |
| RandomGeneticsPlantsC | 125 | RandomGeneticsPlantsD | 126 |
| RandomGeneticsPlantsE | 127 | Soil | 128 |
| Tree | 129 |  |  |

#### 位置与传送门（location / portal）

| 类名 | typeID |
|------|--------|
| Location | 130 |
| Outside | 131 |
| Room | 132 |
| Universe | 133 |
| Door | 140 |
| LiquidDrain | 141 |
| Portal | 142 |

#### 杂物（misc）

| 类名 | typeID |
|------|--------|
| AluminumFoil | 134 |
| ForkMetal | 135 |
| ForkPlastic | 136 |
| InclinedPlane | 137 |
| PaperClip | 138 |
| Picture | 139 |

#### 物质（substance）

| 类名 | typeID | 说明 |
|------|--------|------|
| AceticAcid | 143 | 醋酸 |
| Air | 144 | 空气 |
| Ash | 145 | 灰烬（燃烧产物） |
| Brick | 146 | 砖 |
| Caesium | 147 | 铯 |
| Gallium | 148 | 镓 |
| Ice | 149 | 冰 |
| IronBlock | 150 | 铁块 |
| Lead | 151 | 铅 |
| Mercury | 152 | 汞 |
| Rubber | 153 | 橡胶 |
| Rust | 154 | 铁锈 |
| SaltWater | 155 | 盐水 |
| Soap | 156 | 肥皂 |
| SoapyWater | 157 | 肥皂水 |
| Sodium | 158 | 钠 |
| SodiumAcetate | 159 | 乙酸钠 |
| SodiumBicarbonate | 160 | 碳酸氢钠 |
| SodiumChloride | 161 | 氯化钠（食盐） |
| SteelBlock | 162 | 钢块 |
| Substance | 163 | 物质抽象类 |
| Sugar | 164 | 糖 |
| SugarWater | 165 | 糖水 |
| Tin | 166 | 锡 |
| Water | 167 | 水 |
| Wood | 168 | 木材 |
| WoodBlock | 169 | 木块 |

#### 食物（food）

| 类名 | typeID | 类名 | typeID |
|------|--------|------|--------|
| Almond | 170 | Apple | 171 |
| AppleJuice | 172 | Apricot | 173 |
| Avocado | 174 | Banana | 175 |
| Bread | 176 | Cashew | 177 |
| Cherry | 178 | Chocolate | 179 |
| Dough | 180 | Flour | 181 |
| Food | 182 | Fruit | 183 |
| FruitSalad | 184 | Garlic | 185 |
| Grapefruit | 186 | IceCream | 187 |
| Jam | 188 | Lemon | 189 |
| Marshmallow | 190 | MixedNuts | 191 |
| Onion | 192 | Orange | 193 |
| OrangeJuice | 194 | Peach | 195 |
| Peanut | 196 | Pear | 197 |
| Potato | 198 | Sandwich | 199 |
| Smores | 200 |  |  |

#### 颜料（paint）

| 类名 | typeID | 类名 | typeID |
|------|--------|------|--------|
| BluePaint | 201 | BlueVioletPaint | 202 |
| BrownPaint | 203 | GreenBluePaint | 204 |
| GreenPaint | 205 | OrangePaint | 206 |
| Paint | 207 | RedOrangePaint | 208 |
| RedPaint | 209 | VioletPaint | 210 |
| VioletRedPaint | 211 | YellowGreenPaint | 212 |
| YellowOrangePaint | 213 | YellowPaint | 214 |

#### 任务物品（taskitems）

| 类名 | typeID |
|------|--------|
| AnswerBox | 215 |
| UnknownSubstanceElectricalConductivity | 216 |
| UnknownSubstanceThermal | 217 |

---

## 4. 物体属性（Properties）

每个 `EnvObject` 都有一组可选属性（Option），在对象树 JSON 中以 `propXxx` 字段呈现。

### 4.1 核心属性清单

| 属性 | Scala 类 | JSON 字段 | 说明 |
|------|----------|-----------|------|
| 物质 | `MaterialProperties` | `propMaterial` | 名称、颜色、温度、物态、熔沸点、燃烧点、导电性、摩擦系数等 |
| 可食用性 | `EdibilityProperties` | `propEdibility` | 是否可吃、是否有毒 |
| 容器 | `ContainerProperties` | `propContainer` | 是否是容器、是否打开、是否可关闭 |
| 设备 | `DeviceProperties` | `propDevice` | 是否可激活、是否已激活、是否可用、是否损坏 |
| 热源 | `HeatSourceProperties` | `propHeatSource` | 最高温度、当前设定温度 |
| 冷源 | `CoolingSourceProperties` | `propCoolingSource` | 最低温度、当前设定温度 |
| 传送门 | `PortalProperties` | `propPortal` | 是否打开、是否可打开、连接的两个位置、是否上锁 |
| 可移动 | `MoveableProperties` | `propMoveable` | 是否可移动 |
| 电气连接 | `ElectricalConnectionProperties` | `propElectricalConnection` | 连接到的其他端子集合 |
| 生命 | `LifeProperties` | `propLife` | 生命类型、温度范围、是否生病/死亡、典型寿命等 |
| 传粉 | `PollinationProperties` | `propPollination` | 花的传粉状态 |

### 4.2 `propMaterial` 字段示例

```json
{
  "substanceName": "cloth",
  "color": "white",
  "temperatureC": 10.0,
  "thermalConductivity": 0.1,
  "stateOfMatter": "solid",
  "boilingPoint": 10001.0,
  "meltingPoint": 10000.0,
  "isCombusting": false,
  "hasCombusted": false,
  "combustionTicks": 100,
  "electricallyConductive": false,
  "frictionCoefficient": 0.3
}
```

### 4.3 `propContainer` 类型

| 类型 | isContainer | isOpen | isClosable | 说明 |
|------|-------------|--------|------------|------|
| `IsContainer` | true | false | true | 可关闭容器（如 fridge） |
| `IsOpenUnclosableContainer` | true | true | false | 始终开放的容器（如 room、counter 表面） |
| `IsNotContainer` | false | - | - | 非容器 |

### 4.4 `propDevice` 示例

```json
{
  "isActivable": true,
  "isActivated": true,
  "isUsable": false,
  "isBroken": false
}
```

### 4.5 `propHeatSource` / `propCoolingSource` 示例

```json
// BlastFurnace
{"maxTemp": 3000.0, "curSetTemp": null}
// Oven
{"maxTemp": 540.0, "curSetTemp": null}
// Freezer
{"minTemp": -18.0, "curSetTemp": -18.0}
// UltraColdFreezer
{"minTemp": -86.0, "curSetTemp": -86.0}
```

### 4.6 `propLife` 示例（bee）

```json
{
  "lifeformType": "bee",
  "minTemp": 0.0,
  "maxTemp": 50.0,
  "isSickly": false,
  "isDead": false,
  "lifespanTypical": 0.1
}
```

---

## 5. 可交互动作（Actions）

### 5.1 动作模板

通过 `get_possible_actions()` 可获取当前支持的动作模板（`OBJ` 为占位符）：

| ID | 模板 | 自然语言触发示例 |
|----|------|------------------|
| 0 | `open OBJ` | open door / open fridge |
| 1 | `close OBJ` | close door / close cupboard |
| 2 | `go OBJ` | go to kitchen / walk through door |
| 3 | `look around` | look around |
| 4 | `look at OBJ` | look at apple |
| 5 | `look in OBJ` | look in fridge |
| 6 | `activate OBJ` | activate stove / turn on oven |
| 7 | `deactivate OBJ` | deactivate freezer / turn off sink |
| 8 | `eat OBJ` | eat apple |
| 9 | `move OBJ to OBJ` | move pot to stove / put apple in bowl |
| 10 | `pour OBJ in OBJ` | pour water in pot |
| 11 | `focus on OBJ` | focus on substance |
| 12 | `reset task` | reset task |
| 13 | `use OBJ on OBJ` | use thermometer on water |
| 14 | `read OBJ` | read book |
| 15 | `flush OBJ` | flush toilet |
| 16 | `connect OBJ to OBJ` | connect wire to battery |
| 17 | `disconnect OBJ` | disconnect wire |
| 18 | `wait` | wait / wait1 |
| 19 | `wait10` | wait 10 |
| 20 | `inventory` | inventory |
| 21 | `pick up OBJ` | pick up apple / get pot |
| 22 | `put down OBJ` | put down apple / drop pot |
| 23 | `mix OBJ` | mix bowl / stir pot |
| 24 | `task` | task description |
| 25 | `teleport to OBJ` | teleport to kitchen（仅在 teleportAction simplification 下） |
| 26 | `dunk OBJ in OBJ` | dunk pot in water |

### 5.2 免费动作

以下动作不推进模拟器 tick，不增加步数：

- `look around`
- `inventory`
- `task description`

### 5.3 动作注册

```scala
def mkActionDefinitions(): ActionHandler = {
  val actionHandler = new ActionHandler()
  ActionOpenDoor.registerAction(actionHandler)
  ActionCloseDoor.registerAction(actionHandler)
  ActionMoveThroughDoor.registerAction(actionHandler)
  ActionLookAround.registerAction(actionHandler)
  ActionLookAt.registerAction(actionHandler)
  ActionLookIn.registerAction(actionHandler)
  ActionActivate.registerAction(actionHandler)
  ActionDeactivate.registerAction(actionHandler)
  ActionEat.registerAction(actionHandler)
  ActionMoveObject.registerAction(actionHandler)
  ActionPourObject.registerAction(actionHandler)
  ActionDunkObject.registerAction(actionHandler)
  ActionFocus.registerAction(actionHandler)
  ActionResetTask.registerAction(actionHandler)
  ActionUseDevice.registerAction(actionHandler)
  ActionRead.registerAction(actionHandler)
  ActionFlush.registerAction(actionHandler)
  if (!noElectricalSimplification) {
    ActionConnectElectrical.registerAction(actionHandler)
    ActionDisconnectElectrical.registerAction(actionHandler)
  }
  ActionWait1.registerAction(actionHandler)
  ActionWait10.registerAction(actionHandler)
  ActionInventory.registerAction(actionHandler)
  ActionPickUpObjectIntoInventory.registerAction(actionHandler)
  ActionPutDownObjectIntoInventory.registerAction(actionHandler)
  ActionMix.registerAction(actionHandler)
  ActionTaskDesc.registerAction(actionHandler)
  if (teleportSimplification) ActionTeleport.registerAction(actionHandler)
  actionHandler
}
```

---

## 6. 状态变化机制

### 6.1 单步执行循环

```scala
def step(userInputStr: String): (String, Double, Boolean) = {
  // 1. 解析输入为 Action
  val (success, statusStr) = processUserInput(inputStr, universe)
  // 2. 执行队列中的动作
  val actionOutStr = actionHandler.runQueuedActions()
  // 3. 动作前检查目标
  task.goalSequence.tick(objMonitor, agent)
  // 4. 若动作耗时，推进世界 tick
  if (willActionsTakeTime) {
    universe.clearTickProcessedRecursive()
    universe.tick()
    SimplifierProcessor.runSimplificationsEachTick(universe, agent)
    curIter += 1
  }
  // 5. 动作后检查目标
  task.goalSequence.tick(objMonitor, agent)
  (outStr, score, isCompleted)
}
```

### 6.2 每 tick 执行的物理/化学/生物过程

每个 `EnvObject.tick()` 会递归执行：

1. **燃烧（Combustion）**
   - 温度 ≥ `combustionPoint` → `isCombusting = true`
   - 每 tick 减少 `combustionTicks`，到 0 时物体被删除并生成 `Ash`
   - 同一容器中的液态水可灭火并变为蒸汽

2. **热传导（HeatTransfer）**
   - 容器与其中的物体发生热交换
   - 容器内物体之间也会发生热交换
   - 温差 × 热导率决定传热量，每步限制在 ±1000°C

3. **物态变化（StateOfMatter）**
   - 温度 < 熔点 → solid
   - 温度 > 沸点 → gas
   - 否则 → liquid
   - 名称会随物态变化：`water` → `ice`（<0°C）→ `steam`（>100°C）

4. **导电性（ElectricalConductivity）**
   - 非极性端子之间自动建立电气连接
   - 设备一端接地、一端有电压时会被激活

5. **生命过程（Life）**
   - 植物有生命周期，tick 推进生长阶段
   - 蜜蜂传粉、遗传交叉等

### 6.3 化学反应（Chemistry）

`mix OBJ` 会触发硬编码配方，例如：

| 反应物 | 产物 |
|--------|------|
| water + sodium chloride | salt water |
| water + soap | soapy water |
| water + flour | dough |
| red paint + blue paint | violet paint |
| bread + peanut | peanut butter sandwich |
| iron block + water | rust |

### 6.4 状态变化实例：加热烤箱

运行时观察到的温度变化：

```
tick 1: air temp = 10.19°C
tick 2: air temp = 10.32°C
tick 3: air temp = 10.43°C
...
tick 10: air temp = 11.01°C
```

烤箱激活后，厨房内空气温度逐渐上升；若将含水的容器放入烤箱，水最终会达到沸点并变为蒸汽。

---

## 7. 任务（Tasks）

`tasks.json` 定义了 30 个任务，涵盖物质、测量、电学、分类、生物、化学、力和遗传学等主题。

| task_id | 主题 | 任务名 | task_name |
|---------|------|--------|-----------|
| 1-1 | Matter | Changes of State (Boiling) | boil |
| 1-2 | Matter | Changes of State (Melting) | melt |
| 1-3 | Matter | Changes of State (Freezing) | freeze |
| 1-4 | Matter | Changes of State (Any) | change-the-state-of-matter-of |
| 2-1 | Measurement | Use Thermometer | use-thermometer |
| 2-2 | Measurement | Measuring Boiling Point (known) | measure-melting-point-known-substance |
| 2-3 | Measurement | Measuring Boiling Point (unknown) | measure-melting-point-unknown-substance |
| 3-1 | Electricity | Create a circuit | power-component |
| 3-2 | Electricity | Renewable vs Non-renewable Energy | power-component-renewable-vs-nonrenewable-energy |
| 3-3 | Electricity | Test Conductivity (known) | test-conductivity |
| 3-4 | Electricity | Test Conductivity (unknown) | test-conductivity-of-unknown-substances |
| 4-1 | Classification | Find a living thing | find-living-thing |
| 4-2 | Classification | Find a non-living thing | find-non-living-thing |
| 4-3 | Classification | Find a plant | find-plant |
| 4-4 | Classification | Find an animal | find-animal |
| 5-1 | Biology | Grow a plant | grow-plant |
| 5-2 | Biology | Grow a fruit | grow-fruit |
| 6-1 | Chemistry | Mixing (generic) | chemistry-mix |
| 6-2 | Chemistry | Mixing paints (secondary colours) | chemistry-mix-paint-secondary-color |
| 6-3 | Chemistry | Mixing paints (tertiary colours) | chemistry-mix-paint-tertiary-color |
| 7-1 | Biology | Identify longest-lived animal | lifespan-longest-lived |
| 7-2 | Biology | Identify shortest-lived animal | lifespan-shortest-lived |
| 7-3 | Biology | Identify longest-then-shortest-lived animal | lifespan-longest-lived-then-shortest-lived |
| 8-1 | Biology | Identify life stages (plant) | identify-life-stages-1 |
| 8-2 | Biology | Identify life stages (animal) | identify-life-stages-2 |
| 9-1 | Forces | Inclined Planes (determine angle) | inclined-plane-determine-angle |
| 9-2 | Forces | Friction (known surfaces) | inclined-plane-friction-named-surfaces |
| 9-3 | Forces | Friction (unknown surfaces) | inclined-plane-friction-unnamed-surfaces |
| 10-1 | Biology | Mendelian Genetics (known plants) | mendelian-genetics-known-plant |
| 10-2 | Biology | Mendelian Genetics (unknown plants) | mendelian-genetics-unknown-plant |

每个任务有多个 `variationIdx`，可通过 `env.get_max_variations(task_name)` 查询。

---

## 8. 简化选项（Simplifications）

通过 `load(..., simplificationStr="...")` 可开启简化：

| 简化项 | 作用 |
|--------|------|
| `teleportAction` | 增加 `teleport to <location>` 动作，可直达任意位置 |
| `selfWateringFlowerPots` | 花盆自动浇水，植物不会枯死 |
| `openContainers` | 所有容器初始为打开状态 |
| `openDoors` | 所有门初始为打开状态 |
| `noElectricalAction` | 移除 `connect` / `disconnect` 动作 |
| `easy` | 同时启用以上所有简化（除 noElectricalAction） |

注意：电气相关任务不能启用 `noElectricalAction`。

---

## 9. Python API 常用方法

```python
from scienceworld import ScienceWorldEnv

env = ScienceWorldEnv(taskName="boil")

# 加载特定变体与简化
env.load(taskName="boil", variationIdx=0, simplificationStr="openDoors")

# 重置并获取初始观察
obs, info = env.reset()

# 单步
obs, reward, done, info = env.step("activate stove")

# 免费观察
env.look()
env.inventory()
env.taskdescription()

# 查询环境元信息
env.get_task_names()
env.get_max_variations("boil")
env.get_possible_actions()
env.get_possible_actions_with_IDs()
env.get_possible_objects()
env.get_valid_action_object_combinations()
env.get_valid_action_object_combinations_with_templates()

# 获取完整对象树（JSON）
tree = env.getObjectTree()

# 目标进度
env.get_goal_progress()

env.close()
```

`step()` 返回的 `info` 包含：

```python
{
  'moves': int,
  'score': int,            # 0-100
  'reward': int,           # 当前步分数增量
  'look': str,
  'inv': str,
  'taskDesc': str,
  'valid': List[str],      # 当前有效动作-对象组合
  'variationIdx': int,
  'taskName': str,
  'simplificationStr': str,
}
```

---

## 10. 对象树结构示例

```json
{
  "uuid": "17199",
  "name": "universe",
  "type": "",
  "isDeleted": false,
  "propMaterial": null,
  "propContainer": {"isContainer": "true", "isOpen": true, "isClosable": false},
  "propDevice": null,
  "propHeatSource": null,
  "propCoolingSource": null,
  "propPortal": null,
  "propMoveable": {"isMovable": false},
  "propElectricalConnection": null,
  "propLife": null,
  "contents": {
    "living room-17301": {
      "uuid": "17301",
      "name": "living room",
      "type": "",
      "propContainer": {"isContainer": "true", "isOpen": true, "isClosable": false},
      "propMoveable": {"isMovable": false},
      "contents": {
        "couch-17307": {
          "name": "couch",
          "propMaterial": {...},
          "propContainer": {"isContainer": "true", "isOpen": true, "isClosable": false},
          "propMoveable": {"isMovable": true},
          "contents": {
            "terminal 2-17306": {...},
            "pillow-17310": {...}
          }
        }
      }
    }
  }
}
```

对象树以嵌套 `contents` 表达“在……里面/上面”；`uuid` 全局唯一；`type` 字段在当前版本通常为空字符串，具体类别需通过 `get_all_object_types_LUTJSON()` 或 `object_type_ids.tsv` 查询。

---

## 11. 关键结论

1. **位置**：固定房屋布局包含 10 个主要区域（kitchen/living room/bedroom/bathroom/workshop/greenhouse/art studio/hallway/outside/foundry），通过可开关的门连接。
2. **物体**：共 218 个物体类，覆盖容器、家具、设备、电气元件、生物、物质、食物、颜料、文档、任务物品等。
3. **属性**：物体通过一组可选属性描述，核心属性包括物质（温度/物态/燃烧点）、容器、设备、热源/冷源、可移动、电气连接、生命等。
4. **动作**：25+ 个自然语言动作模板，涵盖移动、观察、操作容器、使用设备、进食、混合、连接电路等。
5. **状态变化**：每个动作若耗时则触发一次世界 tick，tick 中依次执行燃烧、热传导、物态变化、导电、生命过程；mix 动作可触发硬编码化学反应。
6. **任务**：30 个跨学科任务，每个任务有多个变体，通过 `GoalSequence` 根据当前对象树状态判定分数与完成度。

---

## 12. 参考路径

| 文件 | 路径 |
|------|------|
| Python 封装 | `/home/agiagent/venv_biagentsci/lib/python3.12/site-packages/scienceworld/scienceworld.py` |
| 任务定义 | `/home/agiagent/venv_biagentsci/lib/python3.12/site-packages/scienceworld/tasks.json` |
| 物体类型 ID | `/home/agiagent/venv_biagentsci/lib/python3.12/site-packages/scienceworld/object_type_ids.tsv` |
| 编译后的 Scala 模拟器 | `/home/agiagent/venv_biagentsci/lib/python3.12/site-packages/scienceworld/scienceworld.jar` |
| 本仓库 benchmark runner | `apps/scienceworld/run_all_tasks.py` |
| 本仓库工具封装 | `src/tools/scienceworld_tools.py` |
| 本仓库世界模型评估器 | `apps/scienceworld/world_understanding_evaluator.py` |
| 官方源码 | `https://github.com/allenai/ScienceWorld` |
