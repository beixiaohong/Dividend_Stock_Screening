from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    """用户基础模型"""
    account: str = Field(..., min_length=3, max_length=50, description="登录账号")
    email: str = Field("", max_length=255, description="邮箱地址（选填，注册时可留空）")

class UserCreate(UserBase):
    """用户创建模型"""
    password: str = Field(..., min_length=6, max_length=100, description="登录密码")
    nickname: str = Field(..., min_length=1, max_length=100, description="用户昵称")

class UserLogin(BaseModel):
    """用户登录模型 - 简化版本"""
    account: str
    password: str

class UserUpdate(BaseModel):
    """用户更新模型"""
    nickname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    enable_daily_report: Optional[bool] = None

class UserInDB(UserBase):
    """数据库用户模型"""
    user_id: int
    password_hash: str
    nickname: str
    email_verified: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class UserResponse(UserBase):
    """用户响应模型"""
    user_id: int
    nickname: str
    email_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    """令牌模型"""
    access_token: str
    token_type: str = "bearer"