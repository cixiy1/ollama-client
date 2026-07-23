"""多 Agent 协作系统 — 支持多个 Agent 同时工作，分工协作"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Union
from enum import Enum
from datetime import datetime
import threading
import time


class AgentStatus(Enum):
    """Agent 状态"""
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class AgentRole(Enum):
    """Agent 角色"""
    PLANNER = "planner"      # 规划者
    RESEARCHER = "researcher" # 研究者
    CODER = "coder"          # 编程者
    TESTER = "tester"        # 测试者
    REVIEWER = "reviewer"    # 审查者
    COORDINATOR = "coordinator"  # 协调者


@dataclass
class AgentTask:
    """Agent 任务"""
    id: str
    name: str
    description: str
    role: AgentRole
    assigned_to: str  # agent_id
    status: AgentStatus = AgentStatus.IDLE
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    progress: float = 0.0  # 0.0 - 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "role": self.role.value,
            "assigned_to": self.assigned_to,
            "status": self.status.value,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "dependencies": self.dependencies,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "progress": self.progress
        }


@dataclass
class AgentMessage:
    """Agent 消息"""
    id: str
    from_agent: str
    to_agent: str
    message_type: str  # "task", "result", "error", "coordinate"
    content: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class Agent:
    """Agent 实体"""
    id: str
    name: str
    role: AgentRole
    capabilities: List[str]
    model: str
    config: Dict[str, Any] = field(default_factory=dict)
    status: AgentStatus = AgentStatus.IDLE
    current_task: Optional[str] = None
    performance_metrics: Dict[str, Any] = field(default_factory=dict)
    
    def can_perform(self, task_type: str) -> bool:
        """检查是否能执行特定类型的任务"""
        return task_type in self.capabilities
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "capabilities": self.capabilities,
            "model": self.model,
            "config": self.config,
            "status": self.status.value,
            "current_task": self.current_task,
            "performance_metrics": self.performance_metrics
        }


class AgentOrchestrator:
    """Agent 协调器"""
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.tasks: Dict[str, AgentTask] = {}
        self.messages: List[AgentMessage] = []
        self.task_queue: List[str] = []
        self.completed_tasks: List[str] = []
        self.failed_tasks: List[str] = []
        
        # 消息处理器
        self.message_handlers: Dict[str, Callable] = {}
        
        # 运行状态
        self.running = False
        self.coordinator_agent: Optional[Agent] = None
        
        # 回调函数
        self.task_callbacks: Dict[str, Callable] = {}
        self.message_callbacks: Dict[str, Callable] = {}
    
    def add_agent(self, agent: Agent):
        """添加 Agent"""
        self.agents[agent.id] = agent
        print(f"Agent {agent.name} ({agent.role.value}) 已添加")
    
    def remove_agent(self, agent_id: str):
        """移除 Agent"""
        if agent_id in self.agents:
            agent = self.agents[agent_id]
            if agent.status == AgentStatus.WORKING:
                print(f"警告: Agent {agent.name} 正在工作，无法移除")
                return False
            
            del self.agents[agent_id]
            
            # 取消该 Agent 的任务
            for task_id, task in self.tasks.items():
                if task.assigned_to == agent_id:
                    task.status = AgentStatus.CANCELLED
                    task.completed_at = datetime.now()
            
            print(f"Agent {agent.name} 已移除")
            return True
        
        return False
    
    def create_task(self, name: str, description: str, role: AgentRole,
                   input_data: Dict[str, Any] = None,
                   dependencies: List[str] = None) -> str:
        """创建任务"""
        task_id = str(uuid.uuid4())
        task = AgentTask(
            id=task_id,
            name=name,
            description=description,
            role=role,
            assigned_to="",  # 稍后分配
            input_data=input_data or {},
            dependencies=dependencies or []
        )
        
        self.tasks[task_id] = task
        self.task_queue.append(task_id)
        
        print(f"任务 {name} 已创建 (ID: {task_id})")
        return task_id
    
    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """分配任务给 Agent"""
        if task_id not in self.tasks:
            return False
        
        if agent_id not in self.agents:
            return False
        
        task = self.tasks[task_id]
        agent = self.agents[agent_id]
        
        # 检查 Agent 是否能执行此任务
        if not agent.can_perform(task.role.value):
            return False
        
        # 检查依赖是否完成
        for dep_id in task.dependencies:
            if dep_id not in self.completed_tasks:
                return False
        
        # 分配任务
        task.assigned_to = agent_id
        task.status = AgentStatus.WORKING
        task.started_at = datetime.now()
        agent.current_task = task_id
        agent.status = AgentStatus.WORKING
        
        print(f"任务 {task.name} 已分配给 {agent.name}")
        return True
    
    def start_orchestration(self):
        """开始协调"""
        self.running = True
        
        # 创建协调者 Agent
        if not self.coordinator_agent:
            self.coordinator_agent = Agent(
                id="coordinator",
                name="协调者",
                role=AgentRole.COORDINATOR,
                capabilities=["coordinate", "monitor", "optimize"],
                model="coordinator-model"
            )
            self.add_agent(self.coordinator_agent)
        
        # 启动任务分配循环
        self._task_allocation_loop()
    
    def stop_orchestration(self):
        """停止协调"""
        self.running = False
        print("Agent 协调已停止")
    
    def _task_allocation_loop(self):
        """任务分配循环"""
        if not self.running:
            return
        
        # 分配任务
        self._assign_available_tasks()
        
        # 检查任务完成情况
        self._check_task_completion()
        
        # 继续循环
        threading.Timer(1.0, self._task_allocation_loop).start()
    
    def _assign_available_tasks(self):
        """分配可用任务"""
        available_agents = [
            agent for agent in self.agents.values()
            if agent.status == AgentStatus.IDLE
        ]
        
        for task_id in self.task_queue[:]:
            task = self.tasks[task_id]
            
            # 检查依赖是否完成
            dependencies_met = all(dep_id in self.completed_tasks for dep_id in task.dependencies)
            
            if dependencies_met and available_agents:
                # 找到合适的 Agent
                suitable_agents = [
                    agent for agent in available_agents
                    if agent.can_perform(task.role.value)
                ]
                
                if suitable_agents:
                    # 选择最适合的 Agent（简单策略：选择第一个）
                    agent = suitable_agents[0]
                    self.assign_task(task_id, agent.id)
                    available_agents.remove(agent)
                    self.task_queue.remove(task_id)
    
    def _check_task_completion(self):
        """检查任务完成情况"""
        for task_id, task in self.tasks.items():
            if task.status == AgentStatus.WORKING:
                # 这里应该检查实际的 Agent 执行状态
                # 现在模拟任务完成
                if task.progress >= 1.0:
                    self._complete_task(task_id)
    
    def _complete_task(self, task_id: str):
        """完成任务"""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        agent = self.agents.get(task.assigned_to)
        
        if agent:
            agent.current_task = None
            agent.status = AgentStatus.IDLE
        
        task.status = AgentStatus.COMPLETED
        task.completed_at = datetime.now()
        
        self.completed_tasks.append(task_id)
        
        # 发送完成消息
        message = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=task.assigned_to,
            to_agent="coordinator",
            message_type="result",
            content={"task_id": task_id, "result": task.output_data}
        )
        self.send_message(message)
        
        print(f"任务 {task.name} 已完成")
        
        # 调用回调
        if task_id in self.task_callbacks:
            self.task_callbacks[task_id](task)
    
    def send_message(self, message: AgentMessage):
        """发送消息"""
        self.messages.append(message)
        
        # 调用消息处理器
        if message.message_type in self.message_handlers:
            self.message_handlers[message.message_type](message)
        
        # 调用回调
        if message.id in self.message_callbacks:
            self.message_callbacks[message.id](message)
        
        print(f"消息: {message.from_agent} -> {message.to_agent}: {message.message_type}")
    
    def get_task_status(self, task_id: str) -> Optional[AgentTask]:
        """获取任务状态"""
        return self.tasks.get(task_id)
    
    def get_agent_status(self, agent_id: str) -> Optional[Agent]:
        """获取 Agent 状态"""
        return self.agents.get(agent_id)
    
    def get_overview(self) -> Dict[str, Any]:
        """获取整体概览"""
        return {
            "total_agents": len(self.agents),
            "total_tasks": len(self.tasks),
            "completed_tasks": len(self.completed_tasks),
            "failed_tasks": len(self.failed_tasks),
            "pending_tasks": len(self.task_queue),
            "working_agents": len([a for a in self.agents.values() if a.status == AgentStatus.WORKING]),
            "idle_agents": len([a for a in self.agents.values() if a.status == AgentStatus.IDLE])
        }
    
    def create_team(self, name: str, agent_configs: List[Dict[str, Any]]) -> bool:
        """创建团队"""
        try:
            for config in agent_configs:
                agent = Agent(
                    id=config["id"],
                    name=config["name"],
                    role=AgentRole(config["role"]),
                    capabilities=config["capabilities"],
                    model=config["model"],
                    config=config.get("config", {})
                )
                self.add_agent(agent)
            
            print(f"团队 {name} 已创建，包含 {len(agent_configs)} 个 Agent")
            return True
            
        except Exception as e:
            print(f"创建团队失败: {e}")
            return False
    
    def optimize_task_distribution(self):
        """优化任务分配"""
        # 简单的优化策略：根据 Agent 的性能和负载重新分配
        working_agents = [a for a in self.agents.values() if a.status == AgentStatus.WORKING]
        
        if len(working_agents) > 1:
            # 计算每个 Agent 的工作量
            workloads = {}
            for agent in working_agents:
                tasks = [t for t in self.tasks.values() if t.assigned_to == agent.id]
                workloads[agent.id] = len(tasks)
            
            # 找出工作量和平均负载差异最大的 Agent
            avg_load = sum(workloads.values()) / len(workloads)
            max_deviation = 0
            overloaded_agent = None
            underloaded_agent = None
            
            for agent_id, load in workloads.items():
                deviation = abs(load - avg_load)
                if deviation > max_deviation:
                    max_deviation = deviation
                    if load > avg_load:
                        overloaded_agent = agent_id
                    else:
                        underloaded_agent = agent_id
            
            # 重新分配任务
            if overloaded_agent and underloaded_agent:
                overloaded_tasks = [
                    t for t in self.tasks.values() 
                    if t.assigned_to == overloaded_agent and t.status == AgentStatus.WORKING
                ]
                
                for task in overloaded_tasks[:1]:  # 只移动一个任务
                    if self.assign_task(task.id, underloaded_agent):
                        print(f"重新分配任务: {task.name} 从 {overloaded_agent} 到 {underloaded_agent}")
                        break


# 使用示例
def demo_multi_agent():
    """演示多 Agent 协作"""
    orchestrator = AgentOrchestrator()
    
    # 创建团队
    team_config = [
        {
            "id": "planner_1",
            "name": "规划者 Alice",
            "role": "planner",
            "capabilities": ["plan", "analyze", "coordinate"],
            "model": "planning-model"
        },
        {
            "id": "coder_1", 
            "name": "编程者 Bob",
            "role": "coder",
            "capabilities": ["code", "debug", "test"],
            "model": "coding-model"
        },
        {
            "id": "tester_1",
            "name": "测试者 Charlie", 
            "role": "tester",
            "capabilities": ["test", "validate", "report"],
            "model": "testing-model"
        }
    ]
    
    orchestrator.create_team("开发团队", team_config)
    
    # 创建任务
    task1_id = orchestrator.create_task(
        "项目规划",
        "制定项目开发计划",
        AgentRole.PLANNER,
        {"project_name": "Web应用开发", "requirements": "用户管理功能"}
    )
    
    task2_id = orchestrator.create_task(
        "核心功能开发",
        "实现用户管理功能",
        AgentRole.CODER,
        {"features": ["注册", "登录", "个人资料"]},
        dependencies=[task1_id]  # 依赖规划任务
    )
    
    task3_id = orchestrator.create_task(
        "功能测试",
        "测试用户管理功能",
        AgentRole.TESTER,
        {"test_cases": ["注册测试", "登录测试", "资料更新测试"]},
        dependencies=[task2_id]  # 依赖开发任务
    )
    
    # 开始协调
    orchestrator.start_orchestration()
    
    # 模拟任务执行
    def simulate_task_execution():
        time.sleep(2)  # 模拟规划任务
        
        # 完成规划任务
        task1 = orchestrator.get_task_status(task1_id)
        if task1:
            task1.progress = 1.0
            task1.output_data = {"plan": "分三阶段开发：1.用户管理 2.内容管理 3.系统优化"}
        
        time.sleep(3)  # 模拟开发任务
        
        # 完成开发任务
        task2 = orchestrator.get_task_status(task2_id)
        if task2:
            task2.progress = 1.0
            task2.output_data = {"code": "用户管理模块完成", "files": ["user.py", "auth.py"]}
        
        time.sleep(2)  # 模拟测试任务
        
        # 完成测试任务
        task3 = orchestrator.get_task_status(task3_id)
        if task3:
            task3.progress = 1.0
            task3.output_data = {"test_results": "所有测试通过", "coverage": "95%"}
    
    # 启动模拟
    threading.Thread(target=simulate_task_execution, daemon=True).start()
    
    # 监控进度
    for i in range(10):
        overview = orchestrator.get_overview()
        print(f"第 {i+1} 次检查: {overview}")
        time.sleep(1)
    
    # 停止协调
    orchestrator.stop_orchestration()
    
    return orchestrator


if __name__ == "__main__":
    demo_multi_agent()