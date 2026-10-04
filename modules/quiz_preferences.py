"""Read canonical quiz preferences while preserving imported legacy defaults."""


def category_preferences(settings):
    current = settings.get('quiz') or {}
    old = settings.get('quiz_settings') or {}
    mode = current.get('categories_mode', settings.get('quiz_categories_mode', old.get('default_categories_mode', 'all')))
    pool = current.get('specific_categories', settings.get('quiz_categories_pool', old.get('default_specific_categories', [])))
    count = current.get('num_random_categories', settings.get('num_categories_per_quiz', old.get('default_num_random_categories', 3)))
    return mode, pool or [], count
