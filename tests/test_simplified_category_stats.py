#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест упрощённой системы статистики категорий с threading.Lock
"""

import unittest
import tempfile
import shutil
import os
import json
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch

# Импортируем модули для тестирования
import sys
sys.path.append('.')

from modules.category_manager import CategoryManager
from app_config import AppConfig
from state import BotState


class TestSimplifiedCategoryStats(unittest.TestCase):
    """Тест упрощённой системы статистики категорий"""
    
    def setUp(self):
        """Подготовка тестовой среды"""
        # Создаём временную директорию для тестов
        self.test_dir = tempfile.mkdtemp()
        self.test_data_dir = Path(self.test_dir) / "data"
        self.test_statistics_dir = self.test_data_dir / "statistics"
        self.test_chats_dir = self.test_data_dir / "chats"
        
        # Создаём структуру папок
        self.test_statistics_dir.mkdir(parents=True)
        self.test_chats_dir.mkdir(parents=True)
        
        # Создаём мок для AppConfig
        self.mock_app_config = Mock()
        self.mock_app_config.paths.data = str(self.test_data_dir)
        self.mock_app_config.storage_backend = "json"
        
        # Создаём мок для BotState
        self.mock_state = Mock()
        self.mock_state.quiz_data = {"Космос": [{"question": "Test"}], "История": []}
        
        # Создаём мок для DataManager
        self.mock_data_manager = Mock()
        self.mock_data_manager.statistics_dir = self.test_statistics_dir
        self.mock_data_manager.chats_dir = self.test_chats_dir
        self.mock_data_manager.postgres_storage = None
        self.mock_data_manager.get_global_setting.return_value = {}

        # Initialization loads real fixture files, not an unconfigured Mock.
        self.setup_test_data()
        
        # Создаём CategoryManager
        self.category_manager = CategoryManager(self.mock_state, self.mock_app_config, self.mock_data_manager)
        
    
    def tearDown(self):
        """Очистка после тестов"""
        # Удаляем временную директорию
        shutil.rmtree(self.test_dir)
    
    def setup_test_data(self):
        """Создание тестовых данных"""
        # Создаём глобальную статистику категорий
        global_stats = {
            "Космос": {
                "total_usage": 5,
                "last_used": time.time(),
                "chat_usage": {"123": 3, "456": 2},
                "global_usage": 5,
                "chats_used_in": ["123", "456"]
            },
            "История": {
                "total_usage": 3,
                "last_used": time.time(),
                "chat_usage": {"123": 2, "789": 1},
                "global_usage": 3,
                "chats_used_in": ["123", "789"]
            }
        }
        
        with open(self.test_statistics_dir / "categories_stats.json", 'w', encoding='utf-8') as f:
            json.dump(global_stats, f, ensure_ascii=False, indent=2)
        
        # Создаём чатовую статистику
        chat_stats = {
            "Космос": {
                "total_usage": 3,
                "last_used": time.time(),
                "chat_usage": {"123": 3},
                "global_usage": 3,
                "chats_used_in": ["123"]
            }
        }
        
        test_chat_dir = self.test_chats_dir / "123"
        test_chat_dir.mkdir()
        
        with open(test_chat_dir / "categories_stats.json", 'w', encoding='utf-8') as f:
            json.dump(chat_stats, f, ensure_ascii=False, indent=2)
    
    def test_threading_lock_protection(self):
        """Тест защиты от race conditions с threading.Lock"""
        results = []
        errors = []
        
        def update_category(thread_id):
            """Функция для обновления категории в отдельном потоке"""
            try:
                for i in range(10):
                    self.category_manager._update_category_usage_sync("Тестовая_категория", 123)
                    time.sleep(0.001)  # Небольшая задержка
                results.append(f"Поток {thread_id} завершён успешно")
            except Exception as e:
                errors.append(f"Поток {thread_id} ошибка: {e}")
        
        # Запускаем несколько потоков одновременно
        threads = []
        for i in range(5):
            thread = threading.Thread(target=update_category, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Ждём завершения всех потоков
        for thread in threads:
            thread.join()
        
        # Проверяем, что все потоки завершились без ошибок
        self.assertEqual(len(errors), 0, f"Ошибки в потоках: {errors}")
        self.assertEqual(len(results), 5, "Не все потоки завершились")
        
        # Проверяем, что статистика обновилась корректно
        stats = self.category_manager.get_category_usage_stats_sync()
        self.assertIn("Тестовая_категория", stats)
        self.assertEqual(stats["Тестовая_категория"]["global_usage"], 50)  # 5 потоков × 10 обновлений
        self.assertEqual(stats["Тестовая_категория"]["chat_usage"]["123"], 50)
    
    def test_category_statistics_update(self):
        """Тест обновления статистики категорий"""
        # Обновляем статистику для категории
        self.category_manager._update_category_usage_sync("Новая_категория", 999)
        
        # Проверяем, что статистика обновилась
        stats = self.category_manager.get_category_usage_stats_sync()
        self.assertIn("Новая_категория", stats)
        self.assertEqual(stats["Новая_категория"]["global_usage"], 1)
        self.assertEqual(stats["Новая_категория"]["chat_usage"]["999"], 1)
        self.assertIn("999", stats["Новая_категория"]["chats_used_in"])
    
    def test_data_persistence(self):
        """Тест сохранения данных на диск"""
        # Обновляем статистику
        self.category_manager._update_category_usage_sync("Тест_сохранения", 777)
        
        # Проверяем, что данные сохранились в файл
        global_stats_file = self.test_statistics_dir / "categories_stats.json"
        self.assertTrue(global_stats_file.exists())
        
        with open(global_stats_file, 'r', encoding='utf-8') as f:
            saved_stats = json.load(f)
        
        self.assertIn("Тест_сохранения", saved_stats)
        self.assertEqual(saved_stats["Тест_сохранения"]["global_usage"], 1)
        reloaded = CategoryManager(self.mock_state, self.mock_app_config, self.mock_data_manager)
        self.assertEqual(reloaded.get_category_usage_stats_sync()["Тест_сохранения"]["global_usage"], 1)
    
    def test_chat_specific_stats(self):
        """Тест чат-специфичной статистики"""
        # Обновляем статистику для конкретного чата
        self.category_manager._update_category_usage_sync("Чат_категория", 888)
        
        # Проверяем, что чатовая статистика сохранилась
        chat_stats_file = self.test_chats_dir / "888" / "categories_stats.json"
        self.assertTrue(chat_stats_file.exists())
        
        with open(chat_stats_file, 'r', encoding='utf-8') as f:
            chat_stats = json.load(f)
        
        self.assertIn("Чат_категория", chat_stats)
        self.assertEqual(chat_stats["Чат_категория"]["chat_usage"], 1)
        self.assertEqual(self.category_manager.get_category_usage_stats_sync()["Чат_категория"]["chat_usage"]["888"], 1)
    
    def test_weighted_random_categories(self):
        """Тест взвешенного выбора категорий"""
        # Обновляем статистику для нескольких категорий
        self.category_manager._update_category_usage_sync("Часто_используемая", 111)
        self.category_manager._update_category_usage_sync("Часто_используемая", 111)
        self.category_manager._update_category_usage_sync("Редко_используемая", 111)
        
        # Выбираем категории с учётом весов
        categories = ["Часто_используемая", "Редко_используемая", "Новая_категория"]
        selected = self.category_manager._get_weighted_random_categories(categories, 2, 111)
        
        # Проверяем, что выбрано нужное количество
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(cat in categories for cat in selected))
        self.assertEqual(len(set(selected)), 2)
        self.assertIn("Новая_категория", selected)
        self.assertEqual(self.category_manager._get_weighted_random_categories(categories, 0, 111), [])
        self.assertEqual(self.category_manager._get_weighted_random_categories(["A", "A", "B"], 3, 111), ["A", "B"])
    
    def test_data_integrity(self):
        """Тест целостности данных"""
        # Обновляем статистику
        self.category_manager._update_category_usage_sync("Тест_целостности", 555)
        
        # Проверяем структуру данных
        stats = self.category_manager.get_category_usage_stats_sync()
        category_data = stats["Тест_целостности"]
        
        required_fields = ["total_questions", "last_used", "chat_usage", "global_usage", "chats_used_in"]
        for field in required_fields:
            self.assertIn(field, category_data, f"Отсутствует поле: {field}")
        
        # Проверяем типы данных
        self.assertIsInstance(category_data["global_usage"], int)
        self.assertIsInstance(category_data["total_questions"], int)
        self.assertIsInstance(category_data["chat_usage"], dict)
        self.assertIsInstance(category_data["chats_used_in"], list)


if __name__ == '__main__':
    # Запускаем тесты
    unittest.main(verbosity=2)
