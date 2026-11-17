-- ============================================================
-- 项目库 tcm 初始化：建库 + 统一知识表 knowledge
-- 执行：mysql -u root -p < sql/01_tcm_schema.sql
-- 说明：源表（fangji / zhongyao / 第三个源）导入本库后视为【只读】，
--       所有清洗结果只写 knowledge，原始表不动，规则改了可重跑。
-- ============================================================

CREATE DATABASE IF NOT EXISTS tcm
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE tcm;

DROP TABLE IF EXISTS knowledge;
CREATE TABLE knowledge (
    id              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    source          VARCHAR(32)  NOT NULL                COMMENT '来源：fangji / zhongyao / 偏方 / doc',
    src_fid         VARCHAR(64)  NOT NULL                COMMENT '源表主键（原表 id），溯源用',
    title           VARCHAR(255)     DEFAULT ''         COMMENT '标题',
    content         MEDIUMTEXT                          COMMENT '正文（清洗后）',
    category        VARCHAR(128)     DEFAULT ''         COMMENT '分类（人工/LLM 打标结果）',
    summary         VARCHAR(1000)    DEFAULT ''         COMMENT '摘要（按 class 提取）',
    keywords        VARCHAR(500)     DEFAULT ''         COMMENT '关键词（按 class 提取）',

    -- 状态机（流程图的门禁就落在这两个字段上）
    review_status   TINYINT      NOT NULL DEFAULT 0      COMMENT '0待复核 1已复核 2已拒绝',
    vector_status   TINYINT      NOT NULL DEFAULT 0      COMMENT '0未入库 1已入库（向量库）',
    confidence      TINYINT               DEFAULT NULL   COMMENT 'LLM 分类置信度 0-100',
    classify_reason VARCHAR(500)          DEFAULT NULL   COMMENT 'LLM 分类理由',

    state           TINYINT      NOT NULL DEFAULT 1      COMMENT '1正常 0停用',
    isDel           TINYINT      NOT NULL DEFAULT 0      COMMENT '0未删 1已删（逻辑删除）',

    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_source_fid (source, src_fid),   -- 幂等核心：重复导入/重跑不会插重
    KEY idx_review (review_status),               -- 待复核列表 / 统计卡片
    KEY idx_vector (vector_status),               -- 增量向量化扫描
    KEY idx_category (category),                  -- 分类筛选
    KEY idx_state (state, isDel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='统一知识表（三源合一）';


-- ------------------------------------------------------------
-- 导入完成后，把存量 3 万多条刷成"已复核"（门禁只对新知识生效）：
-- UPDATE knowledge SET review_status = 1 WHERE review_status = 0;
-- ------------------------------------------------------------
