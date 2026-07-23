"""Agent 通信系统 — Agent 之间可以共享状态和消息"""
from __future__ import annotations

import json
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Union
from enum import Enum
from datetime import datetime
import threading
import queue
import time


class MessageType(Enum):
    """消息类型"""
    TASK = "task"           # 任务消息
    RESULT = "result"       # 结果消息
    ERROR = "error"         # 错误消息
    COORDINATE = "coordinate"  # 协调消息
    STATUS = "status"       # 状态消息
    HEARTBEAT = "heartbeat"  # 心跳消息
    BROADCAST = "broadcast"  # 广播消息
    DIRECT = "direct"       # 直接消息


@dataclass
class AgentMessage:
    """Agent 消息"""
    id: str
    from_agent: str
    to_agent: str  # 可以是 "all" 表示广播
    message_type: MessageType
    content: Dict[str, Any]
    priority: int = 0  # 优先级，0-9，9最高
    timestamp: datetime = field(default_factory=datetime.now)
    ttl: int = 3600  # 生存时间（秒），默认1小时
    reply_to: Optional[str] = None  # 回复的消息ID
    correlation_id: Optional[str] = None  # 关联ID，用于跟踪对话
    
    def is_expired(self) -> bool:
        """检查消息是否过期"""
        return (datetime.now() - self.timestamp).total_seconds() > self.ttl
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type.value,
            "content": self.content,
            "priority": self.priority,
            "timestamp": self.timestamp.isoformat(),
            "ttl": self.ttl,
            "reply_to": self.reply_to,
            "correlation_id": self.correlation_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentMessage':
        return cls(
            id=data["id"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            message_type=MessageType(data["message_type"]),
            content=data["content"],
            priority=data.get("priority", 0),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            ttl=data.get("ttl", 3600),
            reply_to=data.get("reply_to"),
            correlation_id=data.get("correlation_id")
        )


@dataclass
class AgentState:
    """Agent 状态"""
    agent_id: str
    status: str
    current_task: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    performance_metrics: Dict[str, Any] = field(default_factory=dict)
    last_heartbeat: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "current_task": self.current_task,
            "capabilities": self.capabilities,
            "performance_metrics": self.performance_metrics,
            "last_heartbeat": self.last_heartbeat.isoformat()
        }


@dataclass
class SharedState:
    """共享状态"""
    key: str
    value: Any
    owner: str  # 谁创建了这个状态
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    access_agents: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
            "access_count": self.access_count,
            "access_agents": self.access_agents
        }


class MessageBroker:
    """消息代理"""
    
    def __init__(self):
        self.message_queues: Dict[str, queue.Queue] = {}  # 每个Agent一个队列
        self.broadcast_queue = queue.Queue()
        self.message_handlers: Dict[str, Callable] = {}
        self.message_history: List[AgentMessage] = []
        self.max_history = 1000
        
        # 运行状态
        self.running = False
        self.worker_thread = None
        
        # 统计
        self.message_stats = {
            "sent": 0,
            "received": 0,
            "processed": 0,
            "failed": 0
        }
    
    def start(self):
        """启动消息代理"""
        self.running = True
        self.worker_thread = threading.Thread(target=self._message_worker, daemon=True)
        self.worker_thread.start()
        print("消息代理已启动")
    
    def stop(self):
        """停止消息代理"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join()
        print("消息代理已停止")
    
    def register_agent(self, agent_id: str):
        """注册Agent"""
        if agent_id not in self.message_queues:
            self.message_queues[agent_id] = queue.Queue()
            print(f"Agent {agent_id} 已注册")
    
    def unregister_agent(self, agent_id: str):
        """注销Agent"""
        if agent_id in self.message_queues:
            del self.message_queues[agent_id]
            print(f"Agent {agent_id} 已注销")
    
    def send_message(self, message: AgentMessage):
        """发送消息"""
        try:
            # 添加到历史
            self.message_history.append(message)
            if len(self.message_history) > self.max_history:
                self.message_history.pop(0)
            
            # 更新统计
            self.message_stats["sent"] += 1
            
            # 根据目标类型分发消息
            if message.to_agent == "all":
                # 广播消息
                self.broadcast_queue.put(message)
            else:
                # 直接消息
                if message.to_agent in self.message_queues:
                    self.message_queues[message.to_agent].put(message)
                else:
                    print(f"目标Agent {message.to_agent} 不存在")
                    self.message_stats["failed"] += 1
            
            print(f"消息已发送: {message.from_agent} -> {message.to_agent}")
            
        except Exception as e:
            print(f"发送消息失败: {e}")
            self.message_stats["failed"] += 1
    
    def receive_message(self, agent_id: str, timeout: float = 1.0) -> Optional[AgentMessage]:
        """接收消息"""
        if agent_id not in self.message_queues:
            return None
        
        try:
            message = self.message_queues[agent_id].get(timeout=timeout)
            self.message_stats["received"] += 1
            return message
        except queue.Empty:
            return None
    
    def broadcast_message(self, from_agent: str, message_type: MessageType, 
                          content: Dict[str, Any], priority: int = 0):
        """广播消息"""
        message = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent="all",
            message_type=message_type,
            content=content,
            priority=priority
        )
        self.send_message(message)
    
    def reply_to_message(self, original_message: AgentMessage, reply_content: Dict[str, Any],
                        message_type: MessageType = MessageType.RESULT) -> AgentMessage:
        """回复消息"""
        reply_message = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=original_message.to_agent,
            to_agent=original_message.from_agent,
            message_type=message_type,
            content=reply_content,
            reply_to=original_message.id,
            correlation_id=original_message.correlation_id
        )
        self.send_message(reply_message)
        return reply_message
    
    def _message_worker(self):
        """消息处理工作线程"""
        while self.running:
            try:
                # 处理广播消息
                try:
                    broadcast_msg = self.broadcast_queue.get(timeout=0.1)
                    for agent_id, msg_queue in self.message_queues.items():
                        if agent_id != broadcast_msg.from_agent:  # 不回发给发送者
                            msg_queue.put(broadcast_msg)
                    self.message_stats["processed"] += 1
                except queue.Empty:
                    pass
                
                # 处理消息处理器
                for message_type, handler in self.message_handlers.items():
                    # 这里可以添加批量处理逻辑
                    pass
                
            except Exception as e:
                print(f"消息处理错误: {e}")
    
    def add_message_handler(self, message_type: MessageType, handler: Callable):
        """添加消息处理器"""
        self.message_handlers[message_type.value] = handler
        print(f"已添加消息处理器: {message_type.value}")
    
    def get_message_history(self, agent_id: str = None, limit: int = 50) -> List[AgentMessage]:
        """获取消息历史"""
        if agent_id:
            # 获取特定Agent的消息
            agent_messages = []
            for msg in self.message_history:
                if msg.from_agent == agent_id or msg.to_agent == agent_id:
                    agent_messages.append(msg)
            return agent_messages[-limit:]
        else:
            # 获取所有消息
            return self.message_history[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.message_stats,
            "registered_agents": len(self.message_queues),
            "message_history_size": len(self.message_history)
        }


class StateManager:
    """状态管理器"""
    
    def __init__(self):
        self.shared_states: Dict[str, SharedState] = {}
        self.agent_states: Dict[str, AgentState] = {}
        self.state_locks: Dict[str, threading.Lock] = {}
        self.observers: Dict[str, List[Callable]] = {}
    
    def create_state(self, key: str, value: Any, owner: str) -> bool:
        """创建共享状态"""
        try:
            if key in self.shared_states:
                return False
            
            state = SharedState(
                key=key,
                value=value,
                owner=owner
            )
            self.shared_states[key] = state
            self.state_locks[key] = threading.Lock()
            
            # 通知观察者
            self._notify_observers(key, "created", state)
            
            print(f"共享状态已创建: {key} (by {owner})")
            return True
            
        except Exception as e:
            print(f"创建状态失败: {e}")
            return False
    
    def get_state(self, key: str, agent_id: str) -> Optional[Any]:
        """获取共享状态"""
        try:
            with self.state_locks[key]:
                state = self.shared_states.get(key)
                if state:
                    state.access_count += 1
                    if agent_id not in state.access_agents:
                        state.access_agents.append(agent_id)
                    return state.value
                return None
                
        except Exception as e:
            print(f"获取状态失败: {e}")
            return None
    
    def update_state(self, key: str, value: Any, agent_id: str) -> bool:
        """更新共享状态"""
        try:
            with self.state_locks[key]:
                if key not in self.shared_states:
                    return False
                
                state = self.shared_states[key]
                state.value = value
                state.modified_at = datetime.now()
                state.access_agents.append(agent_id)
                
                # 通知观察者
                self._notify_observers(key, "updated", state)
                
                print(f"共享状态已更新: {key} (by {agent_id})")
                return True
                
        except Exception as e:
            print(f"更新状态失败: {e}")
            return False
    
    def delete_state(self, key: str, agent_id: str) -> bool:
        """删除共享状态"""
        try:
            with self.state_locks[key]:
                if key not in self.shared_states:
                    return False
                
                state = self.shared_states[key]
                if state.owner != agent_id:
                    return False
                
                del self.shared_states[key]
                del self.state_locks[key]
                
                # 通知观察者
                self._notify_observers(key, "deleted", state)
                
                print(f"共享状态已删除: {key} (by {agent_id})")
                return True
                
        except Exception as e:
            print(f"删除状态失败: {e}")
            return False
    
    def list_states(self, agent_id: str = None) -> List[Dict[str, Any]]:
        """列出共享状态"""
        states = []
        for key, state in self.shared_states.items():
            if agent_id is None or state.owner == agent_id:
                states.append(state.to_dict())
        return states
    
    def register_agent_state(self, agent_id: str, status: str, capabilities: List[str]):
        """注册Agent状态"""
        self.agent_states[agent_id] = AgentState(
            agent_id=agent_id,
            status=status,
            capabilities=capabilities
        )
        print(f"Agent状态已注册: {agent_id}")
    
    def update_agent_state(self, agent_id: str, status: str = None, 
                          current_task: str = None, capabilities: List[str] = None):
        """更新Agent状态"""
        if agent_id not in self.agent_states:
            return
        
        agent_state = self.agent_states[agent_id]
        
        if status:
            agent_state.status = status
        if current_task:
            agent_state.current_task = current_task
        if capabilities:
            agent_state.capabilities = capabilities
        
        agent_state.last_heartbeat = datetime.now()
    
    def get_agent_state(self, agent_id: str) -> Optional[AgentState]:
        """获取Agent状态"""
        return self.agent_states.get(agent_id)
    
    def get_all_agent_states(self) -> Dict[str, AgentState]:
        """获取所有Agent状态"""
        return self.agent_states.copy()
    
    def add_observer(self, key: str, callback: Callable):
        """添加状态观察者"""
        if key not in self.observers:
            self.observers[key] = []
        self.observers[key].append(callback)
    
    def remove_observer(self, key: str, callback: Callable):
        """移除状态观察者"""
        if key in self.observers and callback in self.observers[key]:
            self.observers[key].remove(callback)
    
    def _notify_observers(self, key: str, event: str, state: SharedState):
        """通知观察者"""
        if key in self.observers:
            for callback in self.observers[key]:
                try:
                    callback(key, event, state)
                except Exception as e:
                    print(f"观察者回调错误: {e}")


class CommunicationSystem:
    """通信系统 - 整合消息代理和状态管理"""
    
    def __init__(self):
        self.broker = MessageBroker()
        self.state_manager = StateManager()
        self.agent_registry = {}
        
        # 系统回调
        self.message_callbacks = {}
        self.state_callbacks = {}
    
    def start(self):
        """启动通信系统"""
        self.broker.start()
        print("通信系统已启动")
    
    def stop(self):
        """停止通信系统"""
        self.broker.stop()
        print("通信系统已停止")
    
    def register_agent(self, agent_id: str, capabilities: List[str], status: str = "idle"):
        """注册Agent"""
        self.broker.register_agent(agent_id)
        self.state_manager.register_agent_state(agent_id, status, capabilities)
        self.agent_registry[agent_id] = {
            "capabilities": capabilities,
            "status": status,
            "registered_at": datetime.now()
        }
        print(f"Agent {agent_id} 已注册到通信系统")
    
    def unregister_agent(self, agent_id: str):
        """注销Agent"""
        self.broker.unregister_agent(agent_id)
        if agent_id in self.agent_registry:
            del self.agent_registry[agent_id]
        print(f"Agent {agent_id} 已从通信系统注销")
    
    def send_direct_message(self, from_agent: str, to_agent: str, 
                           message_type: MessageType, content: Dict[str, Any],
                           priority: int = 0, correlation_id: str = None) -> AgentMessage:
        """发送直接消息"""
        message = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            priority=priority,
            correlation_id=correlation_id
        )
        self.broker.send_message(message)
        return message
    
    def send_broadcast_message(self, from_agent: str, message_type: MessageType,
                             content: Dict[str, Any], priority: int = 0):
        """发送广播消息"""
        self.broker.broadcast_message(from_agent, message_type, content, priority)
    
    def create_shared_state(self, key: str, value: Any, agent_id: str) -> bool:
        """创建共享状态"""
        return self.state_manager.create_state(key, value, agent_id)
    
    def update_shared_state(self, key: str, value: Any, agent_id: str) -> bool:
        """更新共享状态"""
        return self.state_manager.update_state(key, value, agent_id)
    
    def get_shared_state(self, key: str, agent_id: str) -> Optional[Any]:
        """获取共享状态"""
        return self.state_manager.get_state(key, agent_id)
    
    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent状态"""
        state = self.state_manager.get_agent_state(agent_id)
        if state:
            return state.to_dict()
        return None
    
    def get_system_overview(self) -> Dict[str, Any]:
        """获取系统概览"""
        return {
            "registered_agents": len(self.agent_registry),
            "shared_states": len(self.state_manager.shared_states),
            "message_stats": self.broker.get_stats(),
            "agent_states": self.state_manager.get_all_agent_states()
        }
    
    def monitor_heartbeats(self, timeout: int = 30):
        """监控心跳"""
        while True:
            current_time = datetime.now()
            
            for agent_id, agent_state in self.state_manager.get_all_agent_states().items():
                time_since_heartbeat = (current_time - agent_state.last_heartbeat).total_seconds()
                
                if time_since_heartbeat > timeout:
                    print(f"警告: Agent {agent_id} 心跳超时 ({time_since_heartbeat:.1f}s)")
                    # 可以在这里添加自动重连或清理逻辑
            
            time.sleep(10)  # 每10秒检查一次


# 使用示例
def demo_communication():
    """演示通信系统"""
    comm_system = CommunicationSystem()
    comm_system.start()
    
    # 注册Agent
    comm_system.register_agent("planner_1", ["plan", "analyze"], "idle")
    comm_system.register_agent("coder_1", ["code", "debug"], "idle")
    comm_system.register_agent("tester_1", ["test", "validate"], "idle")
    
    # 创建共享状态
    comm_system.create_shared_state("project_plan", "分阶段开发", "planner_1")
    comm_system.create_shared_state("code_quality", "良好", "coder_1")
    
    # 发送直接消息
    msg1 = comm_system.send_direct_message(
        "planner_1", "coder_1", MessageType.TASK,
        {"task": "实现用户管理", "deadline": "2024-01-15"}
    )
    
    # 发送广播消息
    comm_system.send_broadcast_message(
        "coordinator", MessageType.COORDINATE,
        {"action": "start_development", "priority": "high"}
    )
    
    # 更新共享状态
    comm_system.update_shared_state("code_quality", "优秀", "coder_1")
    
    # 模拟消息处理
    def process_messages():
        time.sleep(1)
        
        # 模拟coder_1回复
        comm_system.send_direct_message(
            "coder_1", "planner_1", MessageType.RESULT,
            {"result": "用户管理功能已完成", "status": "success"},
            correlation_id=msg1.correlation_id
        )
        
        # 模拟tester_1请求状态
        comm_system.send_direct_message(
            "tester_1", "planner_1", MessageType.STATUS,
            {"request": "获取项目计划"}
        )
    
    threading.Thread(target=process_messages, daemon=True).start()
    
    # 监控一段时间
    for i in range(5):
        overview = comm_system.get_system_overview()
        print(f"第 {i+1} 次检查: {overview}")
        time.sleep(2)
    
    comm_system.stop()
    return comm_system


if __name__ == "__main__":
    demo_communication()