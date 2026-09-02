/*
 Navicat MySQL Dump SQL

 Source Server         : MySQL
 Source Server Type    : MySQL
 Source Server Version : 80040 (8.0.40)
 Source Host           : localhost:3306
 Source Schema         : graduation

 Target Server Type    : MySQL
 Target Server Version : 80040 (8.0.40)
 File Encoding         : 65001

 Date: 02/09/2026 23:07:04
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `created_at` datetime(6) NOT NULL,
  `password_hash` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `username` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `nickname` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `phone` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `email` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `UKr43af9ap4edm43mmtq01oddj6`(`username` ASC) USING BTREE,
  UNIQUE INDEX `uk_users_phone`(`phone` ASC) USING BTREE,
  UNIQUE INDEX `uk_users_email`(`email` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 5 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of users
-- ----------------------------
INSERT INTO `users` VALUES (1, '2026-08-29 10:23:55.996894', '$2a$10$VjA9x.GQ.HB.aU.xDnPgDeQp8iKFk92RcjyC9CoZZVjpAID9U3ZRy', 'admin', '管理员', '13800000000', 'admin@star.com');
INSERT INTO `users` VALUES (2, '2026-08-29 18:37:12.000000', '$2a$10$VjA9x.GQ.HB.aU.xDnPgDeQp8iKFk92RcjyC9CoZZVjpAID9U3ZRy', '123456', 'zt', '15548157447', '1511008618@163.com');
INSERT INTO `users` VALUES (3, '2026-08-29 14:00:20.535126', '$2a$10$v7cmyfimioAYKER6Rp.HW.3V3ps1oPHPf.yGlM08v2CMqV/muGE.q', 'testuser1', '测试用户', '13911112222', 'test1@example.com');
INSERT INTO `users` VALUES (4, '2026-08-29 14:05:02.610213', '$2a$10$KOf6k5aS8XwVK8fnSc8xkeg01mkN9GKZDQMJ7hAQR4jlBjrxlh.ye', '1234567', 'zt', '15548157446', 'zt1511008618@163.com');

SET FOREIGN_KEY_CHECKS = 1;
