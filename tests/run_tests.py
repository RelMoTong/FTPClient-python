import unittest
import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 发现和加载测试用例
test_loader = unittest.TestLoader()
test_dir = os.path.dirname(os.path.abspath(__file__))
test_suite = test_loader.discover(test_dir, pattern="test_*.py")

# 创建测试运行器
test_runner = unittest.TextTestRunner(verbosity=2)

# 运行测试
if __name__ == "__main__":
    print("======================================")
    print("正在运行FTP客户端单元测试")
    print("======================================")
    test_result = test_runner.run(test_suite)
    
    # 输出摘要
    print("\n测试摘要:")
    print(f"运行的测试用例: {test_result.testsRun}")
    print(f"通过: {test_result.testsRun - len(test_result.errors) - len(test_result.failures)}")
    print(f"失败: {len(test_result.failures)}")
    print(f"错误: {len(test_result.errors)}")
    
    # 如果有失败或错误，以非零退出
    if test_result.failures or test_result.errors:
        sys.exit(1)
